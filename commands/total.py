import discord
from discord import app_commands, Interaction, Embed, ui
from core.db import get_all_characters_grouped_by_adventure


class PaginationView(ui.View):
    def __init__(self, embeds: list[list[Embed]], user_id: int):
        super().__init__(timeout=60)
        self.embeds = embeds  # 2D 리스트: page -> embeds
        self.user_id = user_id
        self.current_page = 0

        self.prev_button = ui.Button(label="⬅️ 이전", style=discord.ButtonStyle.secondary)
        self.next_button = ui.Button(label="다음 ➡️", style=discord.ButtonStyle.secondary)
        self.prev_button.callback = self.go_previous
        self.next_button.callback = self.go_next
        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    async def go_previous(self, interaction: Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⚠️ 본인이 실행한 명령어만 조작할 수 있어요.", ephemeral=True)
            return
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embeds=self.embeds[self.current_page], view=self)

    async def go_next(self, interaction: Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⚠️ 본인이 실행한 명령어만 조작할 수 있어요.", ephemeral=True)
            return
        if self.current_page < len(self.embeds) - 1:
            self.current_page += 1
            await interaction.response.edit_message(embeds=self.embeds[self.current_page], view=self)


@app_commands.command(name="전체조회", description="등록된 모든 캐릭터를 모험단 단위로 조회합니다")
async def total_command(interaction: Interaction):
    await interaction.response.defer(thinking=True)

    grouped_data = await get_all_characters_grouped_by_adventure()
    if not grouped_data:
        await interaction.followup.send("⚠️ 아직 등록된 캐릭터가 없어요.", ephemeral=True)
        return

    # Embed 생성
    all_embeds = []
    for adv_full_name, chars in grouped_data.items():
        desc = "\n".join(f"- {char['character_name']} - {char['job_grow_name']}" for char in chars)
        embed = Embed(
            title=f"📛 모험단: {adv_full_name}",
            description=desc,
            color=discord.Color.green()
        )
        all_embeds.append(embed)

    if len(all_embeds) <= 10:
        # ✅ 10개 이하면 한 번에 출력
        await interaction.followup.send(embeds=all_embeds)
    else:
        # ✅ 10개 초과 시 페이지로 나눠서 출력
        pages = [all_embeds[i:i + 10] for i in range(0, len(all_embeds), 10)]
        view = PaginationView(pages, user_id=interaction.user.id)
        await interaction.followup.send(embeds=pages[0], view=view)
