import asyncio
import base64
import csv
import io
import os
import stat
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import aiosqlite
import discord
import paramiko
from discord import app_commands

from core._sftp_auth import get_passphrase
from core.db import get_all_watch_items, DB_PATH
from core.logger import logger

KST = timezone(timedelta(hours=9))

SFTP_HOST = os.getenv("SFTP_HOST", "")
SFTP_PORT = int(os.getenv("SFTP_PORT", "22"))
SFTP_USER = os.getenv("SFTP_USER", "")
SFTP_KEY_DATA = os.getenv("SFTP_KEY_DATA", "")
SFTP_EXPORT_PATH = os.getenv("SFTP_EXPORT_PATH", "/home/jongwoo/ml-data")

# 환경변수의 키 데이터(base64)를 디코딩하여 임시 파일로 저장
_key_file_path = None
if SFTP_KEY_DATA:
    _tmp = tempfile.NamedTemporaryFile(mode="wb", suffix=".key", delete=False)
    _tmp.write(base64.b64decode(SFTP_KEY_DATA.strip()))
    _tmp.close()
    os.chmod(_tmp.name, stat.S_IRUSR)
    _key_file_path = _tmp.name

UTF8_BOM = b"\xef\xbb\xbf"
CSV_FIELDS = ["item_id", "item_name", "sold_date", "unit_price", "price", "count"]


async def _fetch_export_data(item_id: str | None, days: int | None) -> tuple[list[dict], int]:
    """내보낼 데이터 조회. (rows, total_count) 반환."""
    conditions = []
    params = []

    if item_id:
        conditions.append("aph.item_id = ?")
        params.append(item_id)
    if days:
        cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        conditions.append("aph.sold_date >= ?")
        params.append(cutoff)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row

        cursor = await conn.execute(
            f"SELECT COUNT(*) as cnt FROM auction_price_history aph {where}", params
        )
        total = (await cursor.fetchone())["cnt"]

        cursor = await conn.execute(f"""
            SELECT aph.item_id, aw.item_name, aph.sold_date,
                   aph.unit_price, aph.price, aph.count
            FROM auction_price_history aph
            LEFT JOIN auction_watch_items aw ON aph.item_id = aw.item_id
            {where}
            ORDER BY aw.item_name, aph.sold_date
        """, params)
        rows = await cursor.fetchall()

    return [dict(r) for r in rows], total


def _build_csv(rows: list[dict]) -> bytes:
    """딕셔너리 리스트를 UTF-8 BOM CSV 바이트로 변환."""
    if not rows:
        return b""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for row in rows:
        row["item_name"] = row.get("item_name") or row.get("item_id", "unknown")
        writer.writerow(row)
    return UTF8_BOM + output.getvalue().encode("utf-8")


def _build_per_item_csvs(rows: list[dict]) -> dict[str, bytes]:
    """아이템별 CSV 파일 생성. {safe_name: csv_bytes} 반환."""
    grouped = defaultdict(list)
    for row in rows:
        name = row.get("item_name") or row.get("item_id", "unknown")
        row["item_name"] = name
        grouped[name].append(row)

    result = {}
    for name, item_rows in grouped.items():
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(item_rows)
        safe_name = name.replace("/", "_").replace("\\", "_").replace(" ", "_")
        result[safe_name] = UTF8_BOM + output.getvalue().encode("utf-8")
    return result


def _get_sftp_client():
    """SFTP 클라이언트 연결."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = paramiko.Ed25519Key.from_private_key_file(_key_file_path, password=get_passphrase())
    client.connect(SFTP_HOST, port=SFTP_PORT, username=SFTP_USER, pkey=pkey)
    return client


def _ensure_dir(sftp, path):
    """SFTP 디렉토리 생성 (없으면)."""
    try:
        sftp.stat(path)
    except FileNotFoundError:
        sftp.mkdir(path)


def _upload_single(csv_bytes: bytes, filename: str):
    """단일 CSV 파일 업로드."""
    client = _get_sftp_client()
    try:
        sftp = client.open_sftp()
        try:
            _ensure_dir(sftp, SFTP_EXPORT_PATH)
            with sftp.open(f"{SFTP_EXPORT_PATH}/{filename}", "wb") as f:
                f.write(csv_bytes)
        finally:
            sftp.close()
    finally:
        client.close()


def _upload_per_item(item_csvs: dict[str, bytes], dir_name: str) -> int:
    """아이템별 CSV 파일을 디렉토리에 업로드. 파일 수 반환."""
    client = _get_sftp_client()
    try:
        sftp = client.open_sftp()
        try:
            _ensure_dir(sftp, SFTP_EXPORT_PATH)
            export_dir = f"{SFTP_EXPORT_PATH}/{dir_name}"
            _ensure_dir(sftp, export_dir)
            for name, csv_bytes in item_csvs.items():
                with sftp.open(f"{export_dir}/{name}.csv", "wb") as f:
                    f.write(csv_bytes)
        finally:
            sftp.close()
    finally:
        client.close()
    return len(item_csvs)


def _format_size(size_bytes: int) -> str:
    """바이트를 읽기 좋은 크기로 변환."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


@app_commands.command(name="데이터내보내기", description="경매장 시세 데이터를 빌드서버로 내보냅니다")
@app_commands.describe(
    days="최근 N일 데이터만 (미입력 시 전체)",
    item="특정 아이템만 (미입력 시 전체)"
)
async def export_data(interaction: discord.Interaction,
                      days: int | None = None,
                      item: str | None = None):
    if not all([SFTP_HOST, SFTP_USER, _key_file_path]):
        await interaction.response.send_message(
            "SFTP 접속 정보가 설정되지 않았습니다. 환경변수를 확인해주세요.",
            ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)

    try:
        # 아이템 이름 → ID 변환
        item_id = None
        item_display = "전체"
        if item:
            watch_items = await get_all_watch_items()
            matched = [w for w in watch_items if item in w["item_name"]]
            if not matched:
                await interaction.followup.send(f"'{item}'에 해당하는 감시 아이템을 찾을 수 없습니다.")
                return
            if len(matched) > 1:
                names = "\n".join(f"- {w['item_name']}" for w in matched)
                await interaction.followup.send(
                    f"여러 아이템이 매칭됩니다. 정확한 이름을 입력해주세요:\n{names}"
                )
                return
            item_id = matched[0]["item_id"]
            item_display = matched[0]["item_name"]

        # 데이터 조회
        rows, total = await _fetch_export_data(item_id, days)

        if not rows:
            await interaction.followup.send("내보낼 데이터가 없습니다.")
            return

        now = datetime.now(KST)
        timestamp = now.strftime("%Y%m%d_%H%M%S")

        if item_id:
            # 단일 아이템 → 파일 1개
            csv_bytes = await asyncio.to_thread(_build_csv, rows)
            filename = f"{item_display}_{timestamp}.csv"
            await asyncio.to_thread(_upload_single, csv_bytes, filename)
            size = _format_size(len(csv_bytes))
            location = f"`{SFTP_EXPORT_PATH}/{filename}`"
        else:
            # 전체 → 아이템별 파일 분리
            item_csvs = await asyncio.to_thread(_build_per_item_csvs, rows)
            dir_name = f"export_{timestamp}"
            file_count = await asyncio.to_thread(_upload_per_item, item_csvs, dir_name)
            total_size = sum(len(v) for v in item_csvs.values())
            size = _format_size(total_size)
            location = f"`{SFTP_EXPORT_PATH}/{dir_name}/` ({file_count}개 파일)"

        period = f"최근 {days}일" if days else "전체 기간"

        embed = discord.Embed(
            title="데이터 내보내기 완료",
            color=discord.Color.green()
        )
        embed.add_field(name="아이템", value=item_display, inline=True)
        embed.add_field(name="기간", value=period, inline=True)
        embed.add_field(name="건수", value=f"{total:,}건", inline=True)
        embed.add_field(name="위치", value=location, inline=False)
        embed.add_field(name="크기", value=size, inline=True)
        embed.set_footer(text=f"{now.strftime('%Y-%m-%d %H:%M KST')}")

        await interaction.followup.send(embed=embed)
        logger.info(f"데이터 내보내기 완료: {location} ({total}건, {size})")

    except paramiko.AuthenticationException:
        await interaction.followup.send("SFTP 인증 실패. 접속 정보를 확인해주세요.", ephemeral=True)
        logger.error("데이터 내보내기 실패: SFTP 인증 실패")
    except Exception as e:
        await interaction.followup.send(
            "내보내기 중 오류가 발생했습니다. 로그를 확인해주세요.", ephemeral=True
        )
        logger.error(f"데이터 내보내기 실패: {e}", exc_info=True)
