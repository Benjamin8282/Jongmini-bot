# 베이스 이미지: Python 3.11 사용
FROM python:3.11

# 한글 폰트 설치 (차트 렌더링용)
RUN apt-get update && \
    apt-get install -y --no-install-recommends fonts-nanum && \
    fc-cache -fv && \
    rm -rf /var/lib/apt/lists/*

# matplotlib 폰트 캐시 초기화
RUN rm -rf /root/.cache/matplotlib

# 컨테이너 내 작업 디렉토리 설정
WORKDIR /app

# 현재 프로젝트 전체 복사
COPY . .

# requirements.txt에 명시된 패키지 설치
RUN pip install --no-cache-dir -r requirements.txt

# _sftp_auth.py → .so 컴파일 후 소스 삭제
RUN pip install --no-cache-dir cython setuptools && \
    python setup_sftp_auth.py build_ext --inplace && \
    rm -f core/_sftp_auth.py core/_sftp_auth.c setup_sftp_auth.py && \
    rm -rf build/

# 컨테이너 시작 시 실행할 기본 명령어
CMD ["python", "main.py"]
