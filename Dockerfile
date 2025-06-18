# 베이스 이미지: Python 3.11 사용
FROM python:3.11

# 컨테이너 내 작업 디렉토리 설정
WORKDIR /app

# 현재 프로젝트 전체 복사
COPY . .

# requirements.txt에 명시된 패키지 설치
RUN pip install --no-cache-dir -r requirements.txt

# 컨테이너 시작 시 실행할 기본 명령어
CMD ["python", "main.py"]
