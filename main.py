import discord
import os
import uuid
import asyncio
from discord import app_commands, ui
from discord.ext import commands
from discord.ui import View, Button
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
import firebase_admin
from firebase_admin import credentials, firestore
from myserver import server_on

# =========================
# FIREBASE
# =========================
cred = credentials.Certificate('/etc/secrets/serviceAccountKey.json')
firebase_admin.initialize_app(cred)
db = firestore.client()


# =========================
# BOT
# =========================
class StudentCardBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="SC!", intents=discord.Intents.all(), help_command=None)

    async def on_ready(self):
        activity = discord.CustomActivity(name="/help เพื่อดูวิธีการใช้งาน!")
        await bot.change_presence(activity=activity)

        await self.tree.sync()
        print(f"บอท {self.user} ออนไลน์แล้ว!")


bot = StudentCardBot()


# =========================
# CREATE CARD MODAL
# =========================
class StudentCardModal(discord.ui.Modal, title="กรอกข้อมูลบัตรนักเรียน"):
    name_th = discord.ui.TextInput(label="ชื่อ-สกุล (ภาษาไทย)", required=True)
    name_eng = discord.ui.TextInput(label="ชื่อ-สกุล (ภาษาต่างประเทศ)", required=True)
    date = discord.ui.TextInput(label="วันเกิด", required=True)
    month = discord.ui.TextInput(label="เดือนเกิด", required=True)
    level = discord.ui.TextInput(label="ระดับชั้น", required=True)

    async def on_submit(self, interaction: discord.Interaction):

        user_id = str(interaction.user.id)

        if not self.date.value.isdigit():
            await interaction.response.send_message("วันเกิดต้องเป็นตัวเลขเท่านั้น กรุณาใช้คำสั่งอีกครั้ง", ephemeral=True)
            return

        if not self.month.value.isdigit():
            await interaction.response.send_message("เดือนเกิดต้องเป็นตัวเลขเท่านั้น กรุณาใช้คำสั่งอีกครั้ง", ephemeral=True)
            return

        if not self.level.value.isdigit():
            await interaction.response.send_message("ระดับชั้นต้องเป็นตัวเลขเท่านั้น กรุณาใช้คำสั่งอีกครั้ง", ephemeral=True)
            return

        card_id = str(uuid.uuid4())

        db.collection("student_cards").document(user_id)\
          .collection("cards").document(card_id).set({
            "card_id": card_id,
            "name_th": self.name_th.value,
            "name_eng": self.name_eng.value,
            "date": self.date.value,
            "month": self.month.value,
            "level": self.level.value,
            "profile_image_url": None,
            "program": None,
            "waiting_for_image": False
        })

        db.collection("student_cards").document(user_id)\
          .set({"pending_card_id": card_id}, merge=True)

        await interaction.response.send_message(
            "กรุณาเลือกสาขาของคุณ",
            view=ProgramSelectView(user_id, card_id),
            ephemeral=True
        )


# =========================
# PROGRAM SELECT
# =========================
class ProgramSelectView(discord.ui.View):
    def __init__(self, user_id: str, card_id: str):
        super().__init__(timeout=None)
        self.add_item(ProgramSelect(user_id, card_id))


class ProgramSelect(discord.ui.Select):
    def __init__(self, user_id: str, card_id: str):
        self.user_id = user_id
        self.card_id = card_id

        options = [
            discord.SelectOption(label="⚔️ การ์ดไฟต์เตอร์", value="การ์ดไฟต์เตอร์"),
            discord.SelectOption(label="🔨 เด็คบิลด์เดอร์", value="เด็คบิลด์เดอร์"),
        ]

        super().__init__(placeholder="กรุณาเลือกสาขาของคุณ", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):

        program = self.values[0]

        db.collection("student_cards").document(self.user_id)\
          .collection("cards").document(self.card_id)\
          .update({"program": program})

        await interaction.response.send_message(
            "โปรดส่งรูปภาพที่คุณต้องการใช้บนบัตร (กรอบรูปมีขนาดประมาณ 3:4 ควรเป็นรูปหน้าตรง พื้นหลังสีพื้น)",
            ephemeral=False
        )


# =========================
# VIEW CARD SELECT
# =========================
class CardSelectView(discord.ui.View):
    def __init__(self, user_id: str, cards: list):
        super().__init__(timeout=None)
        self.add_item(CardSelect(user_id, cards))


class CardSelect(discord.ui.Select):
    def __init__(self, user_id: str, cards: list):
        self.user_id = user_id

        options = [
            discord.SelectOption(label=c["name_th"], value=c["card_id"])
            for c in cards
        ]

        super().__init__(placeholder="เลือกบัตรที่ต้องการดู", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):

        card_id = self.values[0]

        await interaction.response.defer(ephemeral=False, thinking=True)

        doc = db.collection("student_cards").document(self.user_id)\
            .collection("cards").document(card_id).get()

        if not doc.exists:
            await interaction.followup.send("ไม่พบข้อมูลบัตรนี้", ephemeral=True)
            return

        data = doc.to_dict()

        card_path = f"{card_id}.png"

        create_student_card(
            card_path,
            data["name_eng"],
            data["name_th"],
            data["date"],
            data["month"],
            data["level"],
            data.get("program", "-"),
            data.get("profile_image_url")
        )

        view = EditCardView(self.user_id, card_id) if str(interaction.user.id) == self.user_id else None

        if view:
            await interaction.followup.send(
                file=discord.File(card_path),
                view=view,
                ephemeral=False
            )
        else:
            await interaction.followup.send(
                file=discord.File(card_path),
                ephemeral=False
            )


# =========================
# EDIT MODAL
# =========================
class EditInfoModal(discord.ui.Modal, title="แก้ไขข้อมูลบัตรนักเรียน"):
    name_th = discord.ui.TextInput(label="ชื่อ-สกุล (ภาษาไทย)", required=False)
    name_eng = discord.ui.TextInput(label="ชื่อ-สกุล (ภาษาต่างประเทศ)", required=False)
    date = discord.ui.TextInput(label="วันเกิด", required=False)
    month = discord.ui.TextInput(label="เดือนเกิด", required=False)
    level = discord.ui.TextInput(label="ระดับชั้น", required=False)

    def __init__(self, user_id: str, card_id: str, message: discord.Message):
        super().__init__()
        self.user_id = user_id
        self.card_id = card_id
        self.message = message

    async def on_submit(self, interaction: discord.Interaction):

        update_data = {}

        if self.name_eng.value.strip():
            update_data["name_eng"] = self.name_eng.value

        if self.name_th.value.strip():
            update_data["name_th"] = self.name_th.value

        if self.date.value.strip():
            if not self.date.value.isdigit():
                await interaction.response.send_message("วันเกิดต้องเป็นตัวเลขเท่านั้น กรุณาใช้คำสั่งอีกครั้ง", ephemeral=True)
                return
            update_data["date"] = self.date.value

        if self.month.value.strip():
            if not self.month.value.isdigit():
                await interaction.response.send_message("เดือนเกิดต้องเป็นตัวเลขเท่านั้น กรุณาใช้คำสั่งอีกครั้ง", ephemeral=True)
                return
            update_data["month"] = self.month.value

        if self.level.value.strip():
            if not self.level.value.isdigit():
                await interaction.response.send_message("ระดับชั้นต้องเป็นตัวเลขเท่านั้น กรุณาใช้คำสั่งอีกครั้ง", ephemeral=True)
                return
            update_data["level"] = self.level.value

        if not update_data:
            await interaction.response.send_message("คุณยังไม่ได้กรอกข้อมูลที่ต้องการแก้ไข", ephemeral=True)
            return

        db.collection("student_cards").document(self.user_id)\
          .collection("cards").document(self.card_id)\
          .update(update_data)

        doc = db.collection("student_cards").document(self.user_id)\
            .collection("cards").document(self.card_id).get()

        data = doc.to_dict()

        card_path = f"{self.card_id}.png"

        create_student_card(
            card_path,
            data["name_eng"],
            data["name_th"],
            data["date"],
            data["month"],
            data["level"],
            data.get("program", "-"),
            data.get("profile_image_url")
        )

        await interaction.response.defer(ephemeral=True)

        await self.message.edit(
            attachments=[discord.File(card_path)],
            view=EditCardView(self.user_id, self.card_id)
        )

        await interaction.followup.send(
            "ข้อมูลของคุณถูกอัปเดตแล้ว!",
            ephemeral=True
        )


# =========================
# EDIT VIEW (FIXED)
# =========================
class EditCardView(discord.ui.View):
    def __init__(self, user_id: str, card_id: str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.card_id = card_id

    @discord.ui.button(label="แก้ไขข้อมูล", style=discord.ButtonStyle.primary)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):

        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("คุณไม่สามารถแก้ไขบัตรของคนอื่นได้!", ephemeral=True)
            return

        await interaction.response.send_modal(
            EditInfoModal(self.user_id, self.card_id, interaction.message)
        )

    @discord.ui.button(label="เปลี่ยนรูปโปรไฟล์", style=discord.ButtonStyle.secondary)
    async def change_image_button(self, interaction: discord.Interaction, button: discord.ui.Button):

        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("คุณไม่สามารถเปลี่ยนรูปของคนอื่นได้!", ephemeral=True)
            return

        db.collection("student_cards").document(self.user_id)\
          .collection("cards").document(self.card_id)\
          .update({"waiting_for_image": True})

        await interaction.response.send_message(
            "ส่งรูปภาพใหม่ที่ต้องการแก้ไข (กรอบรูปมีขนาดประมาณ 3:4 ควรเป็นรูปหน้าตรง พื้นหลังสีพื้น)",
            ephemeral=False
        )

        def check(msg: discord.Message):
            return (
                msg.author.id == interaction.user.id and
                msg.channel.id == interaction.channel.id and
                len(msg.attachments) > 0
            )

        try:
            msg = await interaction.client.wait_for("message", check=check, timeout=120)

            image_url = msg.attachments[0].url

            db.collection("student_cards").document(self.user_id)\
              .collection("cards").document(self.card_id)\
              .update({
                  "profile_image_url": image_url,
                  "waiting_for_image": False
              })

            doc = db.collection("student_cards").document(self.user_id)\
                .collection("cards").document(self.card_id).get()

            data = doc.to_dict()

            card_path = f"{self.card_id}.png"

            create_student_card(
                card_path,
                data["name_eng"],
                data["name_th"],
                data["date"],
                data["month"],
                data["level"],
                data.get("program", "-"),
                data.get("profile_image_url")
            )

            await interaction.message.edit(
                attachments=[discord.File(card_path)],
                view=EditCardView(self.user_id, self.card_id)
            )

            await interaction.followup.send(
                "📷 อัปเดตรูปโปรไฟล์เรียบร้อยแล้ว!",
                ephemeral=False
            )

        except asyncio.TimeoutError:
            db.collection("student_cards").document(self.user_id)\
              .collection("cards").document(self.card_id)\
              .update({"waiting_for_image": False})

            await interaction.followup.send("หมดเวลาในการอัปโหลดรูป กรุณาลองใหม่อีกครั้ง", ephemeral=True)

    @discord.ui.button(label="ลบบัตร", style=discord.ButtonStyle.danger)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):

        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("คุณไม่สามารถลบบัตรของคนอื่นได้!", ephemeral=True)
            return

        await interaction.response.send_message(
            "คุณแน่ใจหรือไม่ว่าต้องการลบบัตรนี้?",
            view=ConfirmDeleteView(self.user_id, self.card_id, interaction.message),
            ephemeral=True
        )


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, user_id: str, card_id: str, message: discord.Message):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.card_id = card_id
        self.message = message

    @discord.ui.button(label="ยืนยันลบ", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):

        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("คุณไม่สามารถกดปุ่มนี้ได้!", ephemeral=True)
            return

        db.collection("student_cards").document(self.user_id)\
          .collection("cards").document(self.card_id).delete()

        await self.message.delete()

        await interaction.response.send_message("ลบบัตรเรียบร้อยแล้ว", ephemeral=True)

        self.stop()

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):

        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("คุณไม่สามารถกดปุ่มนี้ได้!", ephemeral=True)
            return

        await interaction.response.send_message("ยกเลิกการลบแล้ว", ephemeral=True)

        self.stop()


# =========================
# VIEW CARD COMMAND
# =========================
@bot.tree.command(name="viewcard", description="ดูบัตรนักเรียนของคุณหรือของผู้อื่น")
async def viewcard(interaction: discord.Interaction, user: discord.Member = None):

    await interaction.response.defer(ephemeral=True)

    target = user or interaction.user
    user_id = str(target.id)

    docs = db.collection("student_cards").document(user_id)\
        .collection("cards").stream()

    cards = [d.to_dict() for d in docs]

    if not cards:
        msg = "คุณยังไม่มีบัตรนักเรียน ใช้ `/studentcard` เพื่อสร้าง" if user is None else f"{target.mention} ยังไม่มีบัตรนักเรียน"

        await interaction.followup.send(
            msg,
            ephemeral=True
        )
        return

    await interaction.followup.send(
        "กรุณาเลือกบัตรที่ต้องการดู",
        view=CardSelectView(user_id, cards),
        ephemeral=True
    )

# =========================
# CREATE CARD COMMAND
# =========================
@bot.tree.command(name="studentcard", description="สร้างบัตรนักเรียน")
async def studentcard(interaction: discord.Interaction):
    await interaction.response.send_modal(StudentCardModal())


# =========================
# ON MESSAGE IMAGE HANDLER
# =========================
@bot.event
async def on_message(message):

    if message.author.bot:
        return

    user_id = str(message.author.id)

    user_doc = db.collection("student_cards").document(user_id).get()
    if not user_doc.exists:
        return

    pending = user_doc.to_dict().get("pending_card_id")
    if not pending:
        return

    if message.attachments:
        url = message.attachments[0].url

        db.collection("student_cards").document(user_id)\
          .collection("cards").document(pending)\
          .update({
            "profile_image_url": url
          })

        db.collection("student_cards").document(user_id)\
          .set({"pending_card_id": None}, merge=True)

        await message.reply("📷 รูปภาพถูกบันทึกเรียบร้อยแล้ว! ใช้คำสั่ง `/viewcard` เพื่อดูบัตรของคุณ")


# =========================
# CARD GENERATOR
# =========================
def draw_compressed_text(
    base_image,
    text,
    position,
    left_limit,
    font_path,
    font_size,
    fill="black"
):

    font = ImageFont.truetype(font_path, font_size)

    x, y = position

    temp = Image.new("RGBA", base_image.size, (0, 0, 0, 0))

    temp_draw = ImageDraw.Draw(temp)

    temp_draw.text(
        (x, y),
        text,
        font=font,
        fill=fill,
        anchor="ra"
    )

    bbox = temp.getbbox()

    if not bbox:
        return

    text_region = temp.crop(bbox)

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    max_width = x - left_limit

    if text_width > max_width:

        text_region = text_region.resize(
            (max_width, text_height),
            Image.Resampling.LANCZOS
        )

        text_width = max_width

    paste_x = x - text_width
    paste_y = bbox[1]

    base_image.paste(
        text_region,
        (paste_x, paste_y),
        text_region
    )

def create_student_card(card_path, name_eng, name_th, date, month, level, program, profile_image_url):
    """สร้างบัตรนักเรียน พร้อมพื้นหลัง"""

    if os.path.exists(card_path):
        os.remove(card_path)

    if profile_image_url:

        response = requests.get(profile_image_url)
        response.raise_for_status()

        img = Image.open(BytesIO(response.content)).convert("RGBA")

        background_color = (255, 255, 204)
        bg = Image.new("RGBA", img.size, background_color)

        img = Image.alpha_composite(bg, img)

    else:

        img = Image.new("RGBA", (750, 1000), (220, 220, 220, 255))

    background = Image.open("student_card.png")

    width, height = 2000, 1268
    card = background.resize((width, height))
    draw = ImageDraw.Draw(card)
    font1 = ImageFont.truetype("Mitr-Regular.ttf", 90)
    font2 = ImageFont.truetype("Mitr-Regular.ttf", 60)

    draw.text((1000, 500), f"{name_eng}", font=font2, anchor="ra", fill="black")
    draw_compressed_text(card, name_th, (1000, 400), 400, "Mitr-Regular.ttf", 90)
    draw.text((1000, 707), f"{'วันที่ '+date+' เดือน '+month}", font=font1, anchor="ra", fill="black")
    draw.text((1000, 580), f"{'ปี '+level}", font=font1, anchor="ra", fill="black")
    draw.text((1000, 834), f"{program}", font=font1, anchor="ra", fill="black")

    target_w, target_h = 750, 1000

    target_ratio = target_w / target_h
    img_ratio = img.width / img.height

    if img_ratio > target_ratio:

        scale = target_h / img.height
        new_w = int(img.width * scale)

        img = img.resize((new_w, target_h), Image.LANCZOS)

        left = (new_w - target_w) // 2

        img = img.crop((
            left,
            0,
            left + target_w,
            target_h
        ))

    else:

        scale = target_w / img.width
        new_h = int(img.height * scale)

        img = img.resize((target_w, new_h), Image.LANCZOS)

        img = img.crop((
            0,
            0,
            target_w,
            target_h
        ))

    img = add_rounded_corners(img, radius=60)

    card.paste(img, (1130, 135), img)

    card.save(card_path)


def add_rounded_corners(img, radius):
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)

    draw.rounded_rectangle(
        [(0, 0), img.size],
        radius=radius,
        fill=255
    )

    img = img.convert("RGBA")
    img.putalpha(mask)

    return img

# =========================
# ADMIN SLASH COMMAND
# =========================
@bot.tree.command(name="deletecard", description="ลบบัตรนักเรียนของผู้ใช้ (เฉพาะผู้ดูแล)")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)

async def deletecard(interaction: discord.Interaction, user: discord.Member):

    user_id = str(user.id)

    docs = db.collection("student_cards").document(user_id)\
        .collection("cards").stream()

    cards = [d.to_dict() for d in docs]

    if not cards:

        await interaction.response.send_message(
            f"{user.mention} ไม่มีบัตรนักเรียน",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        f"เลือกบัตรของ {user.mention} ที่ต้องการลบ",
        view=AdminDeleteCardSelectView(user_id, cards),
        ephemeral=True
    )

@deletecard.error
async def deletecard_error(interaction: discord.Interaction, error):

    if isinstance(error, app_commands.errors.MissingPermissions):

        await interaction.response.send_message(
            "คุณไม่มีสิทธิ์ใช้คำสั่งนี้",
            ephemeral=True
        )

# =========================
# ADMIN DELETE CARD
# =========================
class AdminDeleteCardSelectView(discord.ui.View):
    def __init__(self, target_user_id: str, cards: list):
        super().__init__(timeout=60)
        self.add_item(AdminDeleteCardSelect(target_user_id, cards))


class AdminDeleteCardSelect(discord.ui.Select):
    def __init__(self, target_user_id: str, cards: list):

        self.target_user_id = target_user_id

        options = [
            discord.SelectOption(
                label=c["name_th"],
                value=c["card_id"]
            )
            for c in cards
        ]

        super().__init__(
            placeholder="เลือกบัตรที่ต้องการลบ",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "คุณไม่มีสิทธิ์ใช้คำสั่งนี้",
                ephemeral=True
            )
            return

        card_id = self.values[0]

        db.collection("student_cards").document(self.target_user_id)\
          .collection("cards").document(card_id).delete()

        await interaction.response.send_message(
            "ลบบัตรเรียบร้อยแล้ว",
            ephemeral=True
        )

# =========================
# Help Command
# =========================
@bot.tree.command(name='help', description='วิธีใช้งานคำสั่งต่างๆ')
async def helpcommand(interaction):
    emmbed = discord.Embed(title='Bot Commands - คำสั่งที่สามารถใช้งานได้ ', description='[ใช้ Slash Command]', color=0xfff8ad, timestamp= discord.utils.utcnow())
    emmbed.add_field(name='General', value='`/studentcard` - เพื่อสร้างบัตรนักเรียน\n`/viewcard [@ผู้ใช้]` - เพื่อดูบัตรนักเรียนของคุณหรือคนอื่น', inline=False)

    await interaction.response.send_message(embed = emmbed)

# =========================
# RUN BOT
# =========================
server_on()
bot.run(os.getenv('TOKEN'))