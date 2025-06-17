import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("NEOPLE_API_KEY")
if API_KEY is None:
    raise ValueError("❌ Environment variable 'NEOPLE_API_KEY' is missing. Please set it before running the script.")

def search_character_with_image(server_id: str, character_name: str, zoom: int = 1):
    """
        네오플 DNF API를 통해 캐릭터 정보를 검색하고,
        이름/레벨/직업/이미지 URL을 출력합니다.

        Parameters:
            server_id (str): 검색할 서버 ID (예: 'cain', 'all')
            character_name (str): 검색할 캐릭터 이름
            zoom (int): 캐릭터 이미지 확대 비율 (1~3)

        Returns:
            None (콘솔에 출력)
    """
    url = f"https://api.neople.co.kr/df/servers/{server_id}/characters"
    params = {
        "characterName": character_name,
        "apikey": API_KEY
    }

    response = requests.get(url, params=params)

    if response.status_code == 200:
        data = response.json()
        if data['rows']:
            print(f"✅ {len(data['rows'])}명의 캐릭터가 검색되었습니다:\n")
            for char in data['rows']:
                char_id = char['characterId']
                char_server_id = char['serverId']
                char_name = char['characterName']
                job_name = char['jobName']
                level = char['level']
                img_url = f"https://img-api.neople.co.kr/df/servers/{char_server_id}/characters/{char_id}?zoom={zoom}"

                print(f"🧙 이름: {char_name} / 직업: {job_name} / 레벨: {level}")
                print(f"🖼️ 이미지: {img_url}\n")
        else:
            print("⚠️ 결과 없음.")
    else:
        print(f"❌ API 오류! 상태코드: {response.status_code}")
        print(response.text)

# 예시 실행
if __name__ == "__main__":
    search_character_with_image("all", "호크시웅", zoom=3)
