"""AWS Bedrock 자캐 AI 커미션 — Claude 묘사 + Stable Image 생성.

2가지 모드(Phase 0 검증 2026-06-24):
  · 장면연출(text2image): Claude 묘사 + 사용자 장면 → Ultra t2i. 자세/배경 자유, 화풍은 반실사 painterly 고정.
  · 화풍변환(img2img 크롭): 원본 렌더를 알파 바운딩박스로 타이트 크롭 → Ultra img2img.
                            자세는 원본 고정, 화풍 선택(anime/watercolor/painterly).

확정 레시피:
  묘사 = Claude Sonnet 4 (us-east-1, raw bytes converse)
  생성 = Stable Image Ultra (us-west-2)
  화풍변환 strength: anime 0.5(앵커 off), watercolor 0.6(앵커 on=묘사 포함), painterly 0.5
  타이트 크롭 필수(여백 제거로 품질·정체성↑), "masterpiece" suffix 필수(제거 시 포토리얼 회귀).

boto3 client 는 스레드 비안전 → 모듈 1회 싱글톤, asyncio.to_thread + Semaphore 로 비동기화.
환경변수 BEDROCK_COMMISSION_ENABLED 가 true 일 때만 기능 활성(미설정 시 커맨드 미등록).
"""
import asyncio
import base64
import io
import json
import os
import random
import re
import threading

from dotenv import load_dotenv

from core.logger import logger

load_dotenv()

# ── 활성 토글: 미설정/false 면 커맨드 미등록(AWS 자격증명 없는 환경 보호) ──
COMMISSION_ENABLED = os.getenv("BEDROCK_COMMISSION_ENABLED", "false").lower() == "true"

# ── 모델/리전 (env override 가능) ──
DESCRIBE_MODEL_ID = os.getenv(
    "BEDROCK_DESCRIBE_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")
DESCRIBE_REGION = os.getenv("BEDROCK_DESCRIBE_REGION", "us-east-1")
IMAGE_MODEL_ID = os.getenv("BEDROCK_IMAGE_MODEL_ID", "stability.stable-image-ultra-v1:1")
IMAGE_REGION = os.getenv("BEDROCK_IMAGE_REGION", "us-west-2")

# ── 동시 호출 제한(부하/비용 보호) ──
_SEM = asyncio.Semaphore(2)

# 해부학 게이트 재생성 최대 시도 횟수(self-correcting generation)
MAX_GEN_ATTEMPTS = 3

# ── 화풍 선택 목록(슬래시 커맨드 노출용 한글 라벨 -> 내부 키) ──
STYLE_LABELS = {
    "반실사": "painterly",
    "애니": "anime",
    "수채화": "watercolor",
}

# 화풍 레시피: 내부 키 -> 스타일 프롬프트·strength·앵커 사용 여부·추가 네거티브
STYLE_RECIPES = {
    "anime": {
        "prompt": ("anime cel-shaded illustration, clean bold lineart, flat vibrant colors, "
                   "2D anime key visual, studio anime art"),
        "strength": 0.45,  # 게이트가 해부학 backstop → 0.45로 화풍 회복(의상 대체로 보존)
        "use_anchor": False,  # 앵커는 정체성↑·화풍↓ → anime 는 화풍 우선이라 생략
        "negative_extra": "3d render, cgi, photorealistic, glossy, realistic skin, photograph",
    },
    "watercolor": {
        "prompt": ("traditional watercolor painting, visible wet brush strokes, paper texture, "
                   "soft pigment bleeding, hand-painted, muted pastel palette"),
        "strength": 0.6,  # 게이트 backstop → 0.6 복원(수채 화풍 발현)
        "use_anchor": True,  # watercolor 는 robust → 묘사 앵커로 정체성 보강
        "negative_extra": "3d render, cgi, photorealistic, glossy, sharp vector lines",
    },
    "painterly": {
        "prompt": "semi-realistic painterly digital art, soft detailed rendering, artstation",
        "strength": 0.45,  # 게이트 backstop → 0.45로 화풍 회복
        "use_anchor": False,
        "negative_extra": "",
    },
}

# 장면연출(text2image)의 고정 화풍 = Ultra 네이티브(유일하게 안정적)
SCENE_STYLE = "semi-realistic painterly digital art, soft detailed rendering, artstation"

BASE_NEGATIVE = (
    "blurry, low quality, pixelated, sprite, jpeg artifacts, deformed, text, watermark, "
    "extra arms, extra limbs, extra hands, missing limbs, mutated hands, malformed limbs, "
    "fused fingers, too many fingers, bad anatomy, disfigured"
)

# 캐릭터 외형 자동 묘사 프롬프트(배경·포즈·캔버스 제외, 외형 키워드만)
DESC_PROMPT = (
    "You are writing a prompt for an AI image generator. Look at this 2D game character render and "
    "describe ONLY the character's visual appearance as one rich English sentence of comma-separated "
    "keywords covering: hair, eyes, headwear or horns, outfit, footwear, weapon, accessories, any "
    "companion creatures, dominant color palette, and overall aesthetic/vibe. "
    "Do NOT mention the background, the pose, or the white canvas. Output only the description, no preamble."
)

# 생성 결과의 해부학 정상 여부 판정 프롬프트(self-correcting generation 게이트)
JUDGE_PROMPT = (
    "You are a strict QA reviewer for AI-generated character illustrations. "
    "Examine ONLY the character's anatomy. Look for these defects: "
    "more than two arms or hands, a missing arm/hand, an arm bent backward unnaturally, "
    "a reversed or twisted head/neck, a hand fused/melted into the weapon, "
    "malformed or extra fingers, or a generally impossible body pose. "
    "Respond with ONLY a JSON object: {\"ok\": true or false, \"reason\": \"short reason\"}. "
    "Set ok=true ONLY when the character has exactly two arms and two hands in a natural, "
    "anatomically possible pose, with the hand holding the weapon clearly distinct from it. "
    "When in doubt, set ok=false. Output only the JSON, no preamble."
)

# ── boto3 client 싱글톤(지연 생성, threading.Lock 더블체크로 초기화 보호) ──
_describe_client = None
_image_client = None
_client_lock = threading.Lock()


def _get_describe_client():
    global _describe_client
    if _describe_client is None:
        with _client_lock:
            if _describe_client is None:
                import boto3
                from botocore.config import Config
                _describe_client = boto3.client(
                    "bedrock-runtime", region_name=DESCRIBE_REGION,
                    config=Config(read_timeout=120, connect_timeout=10,
                                  retries={"max_attempts": 2}))
                logger.info(f"Bedrock 묘사 클라이언트 생성: {DESCRIBE_REGION}")
    return _describe_client


def _get_image_client():
    global _image_client
    if _image_client is None:
        with _client_lock:
            if _image_client is None:
                import boto3
                from botocore.config import Config
                _image_client = boto3.client(
                    "bedrock-runtime", region_name=IMAGE_REGION,
                    config=Config(read_timeout=300, connect_timeout=10,
                                  retries={"max_attempts": 2}))
                logger.info(f"Bedrock 이미지 클라이언트 생성: {IMAGE_REGION}")
    return _image_client


# ── 이미지 전처리 ──
def _flatten_png(png_bytes: bytes, bg=(245, 245, 245)) -> bytes:
    """투명 배경을 단색으로 평탄화(묘사 입력용 raw bytes)."""
    from PIL import Image
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    flat = Image.new("RGB", img.size, bg)
    flat.paste(img, mask=img.split()[3])
    buf = io.BytesIO()
    flat.save(buf, format="PNG")
    return buf.getvalue()


def _preprocess_cropped(png_bytes: bytes, size=1024, bg=(245, 245, 245),
                        blur=0.4, margin=0.06) -> str:
    """알파 바운딩박스로 캐릭터를 타이트 크롭 후 정사각 1024 로 채워 base64 반환(img2img 입력)."""
    from PIL import Image, ImageFilter
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    bbox = img.split()[3].getbbox()  # 비투명(캐릭터) 영역
    if bbox:
        w, h = img.size
        mx = int((bbox[2] - bbox[0]) * margin)
        my = int((bbox[3] - bbox[1]) * margin)
        bbox = (max(0, bbox[0] - mx), max(0, bbox[1] - my),
                min(w, bbox[2] + mx), min(h, bbox[3] + my))
        img = img.crop(bbox)
    flat = Image.new("RGB", img.size, bg)
    flat.paste(img, mask=img.split()[3])
    w, h = flat.size
    side = max(w, h)
    sq = Image.new("RGB", (side, side), bg)
    sq.paste(flat, ((side - w) // 2, (side - h) // 2))
    sq = sq.resize((size, size), Image.LANCZOS)
    if blur > 0:
        sq = sq.filter(ImageFilter.GaussianBlur(blur))
    buf = io.BytesIO()
    sq.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ── Bedrock 동기 호출(스레드에서 실행) ──
def _describe_sync(flat_png: bytes) -> str:
    client = _get_describe_client()
    resp = client.converse(
        modelId=DESCRIBE_MODEL_ID,
        messages=[{"role": "user", "content": [
            {"image": {"format": "png", "source": {"bytes": flat_png}}},
            {"text": DESC_PROMPT},
        ]}],
        inferenceConfig={"maxTokens": 400, "temperature": 0.2},
    )
    return resp["output"]["message"]["content"][0]["text"].strip()


def _invoke_image_sync(body: dict) -> bytes:
    client = _get_image_client()
    resp = client.invoke_model(
        modelId=IMAGE_MODEL_ID, body=json.dumps(body),
        accept="application/json", contentType="application/json")
    out = json.loads(resp["body"].read().decode("utf-8"))
    reasons = out.get("finish_reasons") or [None]
    if reasons[0] is not None:
        raise RuntimeError(f"Stability 필터/실패: {reasons[0]}")
    images = out.get("images") or []
    if not images:
        raise RuntimeError("Stability: 결과 이미지 없음(필터 추정)")
    return base64.b64decode(images[0])


# ── 비동기 공개 API ──
# 세마포어는 상위 함수에서 한 번만 잡아 describe+invoke 를 한 구간으로 묶는다
# (커미션 1건이 슬롯 1개만 연속 점유 → 중복 점유/불필요한 경쟁 방지).
def _log_desc(desc: str):
    preview = desc[:60] + ("..." if len(desc) > 60 else "")
    logger.info(f"캐릭터 자동 묘사 완료: {preview}")


async def describe_character(png_bytes: bytes) -> str:
    """Bedrock Claude vision 으로 캐릭터 외형을 한 문장 영문 묘사로 자동 생성(단독 호출용)."""
    flat = await asyncio.to_thread(_flatten_png, png_bytes)
    async with _SEM:
        desc = await asyncio.to_thread(_describe_sync, flat)
    _log_desc(desc)
    return desc


def _judge_sync(png_bytes: bytes) -> dict:
    client = _get_describe_client()
    resp = client.converse(
        modelId=DESCRIBE_MODEL_ID,
        messages=[{"role": "user", "content": [
            {"image": {"format": "png", "source": {"bytes": png_bytes}}},
            {"text": JUDGE_PROMPT},
        ]}],
        inferenceConfig={"maxTokens": 200, "temperature": 0},
    )
    text = resp["output"]["message"]["content"][0]["text"].strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            return {"ok": bool(data.get("ok")), "reason": str(data.get("reason", ""))}
        except (ValueError, TypeError):
            pass
    # 파싱 실패 시 안전하게 통과(무한 재시도 방지)
    return {"ok": True, "reason": "판정 파싱 실패(통과 처리)"}


async def judge_anatomy(png_bytes: bytes) -> dict:
    """Bedrock Claude vision 으로 생성 이미지의 해부학 정상 여부를 판정. {ok: bool, reason: str}."""
    async with _SEM:
        verdict = await asyncio.to_thread(_judge_sync, png_bytes)
    logger.info(f"해부학 판정: ok={verdict['ok']} ({verdict['reason'][:40]})")
    return verdict


async def generate_scene_commission(png_bytes: bytes, scene: str,
                                    max_attempts: int = MAX_GEN_ATTEMPTS) -> bytes:
    """장면연출: Claude 묘사 + 사용자 장면 → Ultra text2image(자세/배경 자유, 반실사).

    생성 후 해부학 게이트(judge_anatomy)로 판정 → 붕괴 시 다른 seed 로 재생성(최대 max_attempts).
    """
    flat = await asyncio.to_thread(_flatten_png, png_bytes)
    async with _SEM:
        desc = await asyncio.to_thread(_describe_sync, flat)
    _log_desc(desc)
    prompt = f"{desc}, {scene}, {SCENE_STYLE}, full body, highly detailed, masterpiece"

    last_img = None
    for attempt in range(max_attempts):
        body = {
            "prompt": prompt,
            "negative_prompt": BASE_NEGATIVE,
            "aspect_ratio": "2:3",
            "output_format": "png",
            "seed": random.randint(1, 2_000_000_000),
        }
        async with _SEM:
            last_img = await asyncio.to_thread(_invoke_image_sync, body)
        if attempt == max_attempts - 1:
            break  # 마지막 시도는 재생성 불가 → 판정 생략하고 반환
        verdict = await judge_anatomy(last_img)
        if verdict["ok"]:
            logger.info(f"장면연출 생성 완료(시도 {attempt + 1}/{max_attempts}): {len(last_img) // 1024}KB")
            return last_img
        logger.info(f"장면연출 재시도({attempt + 1}/{max_attempts}): {verdict['reason'][:40]}")
    logger.info(f"장면연출 생성 완료(최종 {max_attempts}/{max_attempts}): {len(last_img) // 1024}KB")
    return last_img


async def generate_style_commission(png_bytes: bytes, style: str,
                                    max_attempts: int = MAX_GEN_ATTEMPTS) -> bytes:
    """화풍변환: 원본 크롭 → Ultra img2img(자세 원본 고정, 화풍 anime/watercolor/painterly).

    생성 후 해부학 게이트(judge_anatomy)로 판정 → 붕괴 시 다른 seed 로 재생성(최대 max_attempts).
    """
    if style not in STYLE_RECIPES:
        raise ValueError(f"지원하지 않는 화풍 키: {style!r} (가능: {list(STYLE_RECIPES)})")
    recipe = STYLE_RECIPES[style]
    b64 = await asyncio.to_thread(_preprocess_cropped, png_bytes)

    # 정체성 앵커 묘사는 1회만(재시도마다 재사용)
    parts = []
    if recipe["use_anchor"]:
        flat = await asyncio.to_thread(_flatten_png, png_bytes)
        async with _SEM:
            desc = await asyncio.to_thread(_describe_sync, flat)
        _log_desc(desc)
        parts.append(desc)
    parts.append(recipe["prompt"])
    parts.append("full body, masterpiece")
    prompt = ", ".join(parts)

    negative = BASE_NEGATIVE
    if recipe["negative_extra"]:
        negative += ", " + recipe["negative_extra"]

    last_img = None
    for attempt in range(max_attempts):
        body = {
            "prompt": prompt,
            "image": b64,
            "strength": recipe["strength"],
            "negative_prompt": negative,
            "output_format": "png",
            "seed": random.randint(1, 2_000_000_000),
        }
        async with _SEM:
            last_img = await asyncio.to_thread(_invoke_image_sync, body)
        if attempt == max_attempts - 1:
            break  # 마지막 시도는 재생성 불가 → 판정 생략하고 반환
        verdict = await judge_anatomy(last_img)
        if verdict["ok"]:
            logger.info(f"화풍변환({style}) 생성 완료(시도 {attempt + 1}/{max_attempts}): {len(last_img) // 1024}KB")
            return last_img
        logger.info(f"화풍변환({style}) 재시도({attempt + 1}/{max_attempts}): {verdict['reason'][:40]}")
    logger.info(f"화풍변환({style}) 생성 완료(최종 {max_attempts}/{max_attempts}): {len(last_img) // 1024}KB")
    return last_img
