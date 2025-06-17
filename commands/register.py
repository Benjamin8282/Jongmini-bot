from io import BytesIO

import discord
from discord import app_commands, Interaction, Embed, ui
from core.dnf_api import search_characters, get_character_image_bytes, get_character_details
from core.models import SERVER_CHOICES_KR, SERVER_MAP
from core.db import save_character, register_character  # ✅ DB 저장 함수 추가


# 선택 UI 정의
class CharacterSelect(ui.View):
    def __init__(self, characters, author_id):
        super().__init__(timeout=60)
        self.result = None
        self.selected_character = None
        self.author_id = author_id
        self._characters_map = {
            f'{char["serverId"]}:{char["characterId"]}': char
            for char in characters[:25]
        }

        options = [
            discord.SelectOption(
                label=char["characterName"],
                description=f'{char["jobGrowName"]} (Lv.{char["level"]}) - {SERVER_MAP.get(char["serverId"], char["serverId"])}',
                value=f'{char["serverId"]}:{char["characterId"]}'
            ) for char in characters[:25]
        ]

        self.select = ui.Select(placeholder="등록할 캐릭터를 선택하세요", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("⚠️ 본인이 실행한 명령어만 응답할 수 있어요.", ephemeral=True)
            return

        self.result = self.select.values[0]
        self.selected_character = self._characters_map[self.result]

        # 모험단 정보 추가
        details = await get_character_details(
            self.selected_character["serverId"], self.selected_character["characterId"]
        )
        adventure_name = details.get("adventureName", "알 수 없음")
        self.selected_character["adventureName"] = adventure_name

        server_name_kr = SERVER_MAP.get(
            self.selected_character["serverId"], self.selected_character["serverId"]
        )
        message = (
            f"✅ `{self.selected_character['characterName']} (Lv.{self.selected_character['level']} - {self.selected_character['jobName']})`"
            f" 캐릭터가 선택되었어요.\n"
            f"서버: {server_name_kr}\n"
            f"모험단: {adventure_name}"
        )

        await interaction.response.send_message(message, ephemeral=True)
        self.stop()


# /등록 명령어
@app_commands.command(name="등록", description="DNF 캐릭터를 종미니에 등록합니다")
@app_commands.describe(server="서버를 선택하세요", name="캐릭터 이름")
@app_commands.choices(server=SERVER_CHOICES_KR)
async def register_command(interaction: Interaction, server: app_commands.Choice[str], name: str):
    await interaction.response.defer(thinking=True)

    result = await search_characters(server.value, name)
    if not result or not result.get("rows"):
        await interaction.followup.send("❌ 캐릭터를 찾을 수 없어요.", ephemeral=True)
        return

    characters = result["rows"]
    files = []
    embeds = []

    for idx, char in enumerate(characters[:5]):
        image_bytes = await get_character_image_bytes(char['serverId'], char['characterId'])
        file = discord.File(BytesIO(image_bytes), filename=f"char{idx}.png")
        server_kr = SERVER_MAP.get(char['serverId'], char['serverId'])

        embed = Embed(
            title=f"{char['characterName']} (Lv.{char['level']} - {char['jobGrowName']})",
            description=f"서버: {server_kr}",
            color=discord.Color.blurple()
        )
        embed.set_image(url=f"attachment://char{idx}.png")

        files.append(file)
        embeds.append(embed)

    view = CharacterSelect(characters, interaction.user.id)
    await interaction.followup.send(embeds=embeds, view=view, files=files, ephemeral=True)

    await view.wait()
    if view.selected_character:
        # ✅ 저장 로직: 캐릭터 정보 저장 + 등록자 기록
        await save_character(view.selected_character)
        await register_character(interaction.user.id, view.selected_character["characterId"])
        print(f"👉 저장 완료: {view.selected_character['characterName']} ({view.selected_character['characterId']})")
