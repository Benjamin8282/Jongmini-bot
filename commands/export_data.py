import asyncio
import base64
import io
import os
import stat
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import discord
import paramiko
from discord import app_commands
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side, numbers
from openpyxl.utils import get_column_letter

from core._sftp_auth import get_passphrase
from core.db import get_all_watch_items, get_conn
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

DATA_COLUMNS = ["sold_date", "unit_price", "price", "count"]
DATA_HEADERS = ["거래일시", "단가", "총액", "수량"]

HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center")
LINK_FONT = Font(color="0563C1", underline="single", size=11)
THIN_BORDER = Border(
    bottom=Side(style="thin", color="D9D9D9"),
)
NUM_FMT = '#,##0'


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

    conn = await get_conn()
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


def _safe_sheet_name(name: str) -> str:
    """시트 이름에 사용할 수 없는 문자 제거 (최대 31자)."""
    for ch in r'\/:*?[]':
        name = name.replace(ch, "_")
    return name[:31]


def _style_header(ws, col_count: int):
    """헤더 행 스타일 적용."""
    for col in range(1, col_count + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN


def _auto_width(ws, col_count: int, data_row_count: int):
    """컬럼 너비 자동 조정."""
    for col in range(1, col_count + 1):
        max_len = len(str(ws.cell(row=1, column=col).value or ""))
        for row in range(2, min(data_row_count + 2, 102)):  # 최대 100행 샘플
            val = ws.cell(row=row, column=col).value
            if val is not None:
                max_len = max(max_len, len(str(val)))
        ws.column_dimensions[get_column_letter(col)].width = min(max_len + 4, 30)


def _write_data_sheet(ws, rows: list[dict]):
    """데이터 시트에 행 쓰기."""
    ws.append(DATA_HEADERS)
    _style_header(ws, len(DATA_HEADERS))

    for row in rows:
        ws.append([
            row["sold_date"],
            row["unit_price"],
            row["price"],
            row["count"],
        ])

    # 숫자 컬럼 포맷
    for r in range(2, len(rows) + 2):
        for c in [2, 3, 4]:
            ws.cell(row=r, column=c).number_format = NUM_FMT
        ws.cell(row=r, column=1).border = THIN_BORDER

    _auto_width(ws, len(DATA_HEADERS), len(rows))
    ws.freeze_panes = "A2"


def _write_summary_sheet(ws, item_stats: list[dict], export_time: str, days: int | None):
    """요약 시트 작성 (통계 + 아이템별 시트 하이퍼링크)."""
    # 제목
    ws.append(["경매장 시세 데이터 내보내기"])
    ws.cell(row=1, column=1).font = Font(bold=True, size=16)
    ws.merge_cells("A1:E1")

    ws.append([])
    ws.append(["내보내기 시간", export_time])
    ws.cell(row=3, column=1).font = Font(bold=True)

    period = f"최근 {days}일" if days else "전체 기간"
    ws.append(["기간", period])
    ws.cell(row=4, column=1).font = Font(bold=True)

    total_records = sum(s["count"] for s in item_stats)
    ws.append(["총 거래 건수", total_records])
    ws.cell(row=5, column=1).font = Font(bold=True)
    ws.cell(row=5, column=2).number_format = NUM_FMT

    ws.append(["아이템 종류", len(item_stats)])
    ws.cell(row=6, column=1).font = Font(bold=True)

    # 아이템 목록 테이블
    ws.append([])
    ws.append(["아이템", "거래 건수", "평균 단가", "최저 단가", "최고 단가"])
    _style_header(ws, 5)
    header_row = ws.max_row

    for i, s in enumerate(item_stats):
        row_num = header_row + 1 + i
        sheet_name = s["sheet_name"]

        # 아이템 이름 + 시트 하이퍼링크
        cell = ws.cell(row=row_num, column=1, value=s["name"])
        cell.hyperlink = f"#'{sheet_name}'!A1"
        cell.font = LINK_FONT

        ws.cell(row=row_num, column=2, value=s["count"]).number_format = NUM_FMT
        ws.cell(row=row_num, column=3, value=s["avg_price"]).number_format = NUM_FMT
        ws.cell(row=row_num, column=4, value=s["min_price"]).number_format = NUM_FMT
        ws.cell(row=row_num, column=5, value=s["max_price"]).number_format = NUM_FMT

    _auto_width(ws, 5, len(item_stats) + header_row)
    ws.sheet_properties.tabColor = "4472C4"


def _build_xlsx(rows: list[dict], export_time: str, days: int | None) -> bytes:
    """아이템별 시트 + 요약 시트가 포함된 Excel 파일 생성."""
    # 아이템별 그룹핑
    grouped = defaultdict(list)
    for row in rows:
        name = row.get("item_name") or row.get("item_id", "unknown")
        row["item_name"] = name
        grouped[name].append(row)

    wb = Workbook()

    # 요약 시트 (첫 번째)
    ws_summary = wb.active
    ws_summary.title = "요약"

    # 아이템별 시트 생성 + 통계 수집
    item_stats = []
    for name, item_rows in sorted(grouped.items()):
        sheet_name = _safe_sheet_name(name)
        ws = wb.create_sheet(title=sheet_name)
        _write_data_sheet(ws, item_rows)

        prices = [r["unit_price"] for r in item_rows if r["unit_price"] > 0]
        item_stats.append({
            "name": name,
            "sheet_name": sheet_name,
            "count": len(item_rows),
            "avg_price": round(sum(prices) / len(prices)) if prices else 0,
            "min_price": min(prices) if prices else 0,
            "max_price": max(prices) if prices else 0,
        })

    # 요약 시트 작성
    _write_summary_sheet(ws_summary, item_stats, export_time, days)

    # 바이트로 변환
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _get_sftp_client():
    """SFTP 클라이언트 연결."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = paramiko.Ed25519Key.from_private_key_file(_key_file_path, password=get_passphrase())
    client.connect(SFTP_HOST, port=SFTP_PORT, username=SFTP_USER, pkey=pkey)
    return client


def _upload_file(file_bytes: bytes, filename: str):
    """파일을 SFTP로 업로드."""
    client = _get_sftp_client()
    try:
        sftp = client.open_sftp()
        try:
            try:
                sftp.stat(SFTP_EXPORT_PATH)
            except FileNotFoundError:
                sftp.mkdir(SFTP_EXPORT_PATH)
            with sftp.open(f"{SFTP_EXPORT_PATH}/{filename}", "wb") as f:
                f.write(file_bytes)
        finally:
            sftp.close()
    finally:
        client.close()


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
        export_time = now.strftime("%Y-%m-%d %H:%M:%S KST")

        # Excel 생성
        xlsx_bytes = await asyncio.to_thread(_build_xlsx, rows, export_time, days)
        filename = f"auction_data_{timestamp}.xlsx"

        # SFTP 업로드
        await asyncio.to_thread(_upload_file, xlsx_bytes, filename)

        size = _format_size(len(xlsx_bytes))
        period = f"최근 {days}일" if days else "전체 기간"
        item_count = len(set(
            (r.get("item_name") or r.get("item_id")) for r in rows
        ))

        embed = discord.Embed(
            title="데이터 내보내기 완료",
            color=discord.Color.green()
        )
        embed.add_field(name="아이템", value=item_display, inline=True)
        embed.add_field(name="기간", value=period, inline=True)
        embed.add_field(name="거래 건수", value=f"{total:,}건", inline=True)
        embed.add_field(
            name="파일",
            value=f"`{SFTP_EXPORT_PATH}/{filename}`",
            inline=False
        )
        embed.add_field(name="크기", value=size, inline=True)
        embed.add_field(name="시트", value=f"요약 + {item_count}개 아이템", inline=True)
        embed.set_footer(text=export_time)

        await interaction.followup.send(embed=embed)
        logger.info(f"데이터 내보내기 완료: {filename} ({total}건, {size})")

    except paramiko.AuthenticationException:
        await interaction.followup.send("SFTP 인증 실패. 접속 정보를 확인해주세요.", ephemeral=True)
        logger.error("데이터 내보내기 실패: SFTP 인증 실패")
    except Exception as e:
        await interaction.followup.send(
            "내보내기 중 오류가 발생했습니다. 로그를 확인해주세요.", ephemeral=True
        )
        logger.error(f"데이터 내보내기 실패: {e}", exc_info=True)
