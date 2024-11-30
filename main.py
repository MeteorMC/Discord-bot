import discord
import httpx
import aiomysql
import os
import json
import sys
import server
from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler

if not os.path.isfile("config.json"):
    logger.critical("config.jsonがありません")
    sys.exit(1)

with open("config.json", mode="r", encoding="utf-8") as f:
    conf = json.load(f)

if not conf['discord_token']:
    logger.critical("discord bot tokenがありません")
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    logger.success("success")
    scheduler.start()

@client.event
async def on_message(message: discord.message.Message):
    if message.author.bot:
        return

    if message.channel.id == conf['target_channel']:
        content = message.content
        if len(content) >= 50:
            await message.reply("文字のしきい値が超えています\nサポートにお問い合わせください")
            logger.warning(f"最大文字数は50文字以内 || 文字数: {len(content)}")
            return

        async with httpx.AsyncClient() as client:
            try:
                cmd = None
                r = await client.get(f"https://api.mojang.com/users/profiles/minecraft/{content}")
                if r.status_code != 200:
                    await message.reply(f"{content}のユーザー名は見つかりませんでした\n再度お試しください")
                    return
                for role in message.author.roles:
                    if role.id == conf['target_role1']:
                        cmd = f"lp user {content} parent add vip"
                        plan = "vip"
                        break
                    elif role.id == conf['target_role2']:
                        plan = "vip+"
                        cmd = f"lp user {content} parent add vip+"
                        break
                if not cmd:
                    await message.reply("必要な情報がありません\nサポートにお問い合わせください")
                    logger.error("必要なロールがないため処理を停止")
                    return
            except httpx.RequestError as e:
                await message.reply("内部エラーが発生しました\n再度お試しください")
                logger.error(e)
                return

        try:
            async with aiomysql.connect(host=conf['db_host'], user=conf['db_user'], password=conf['db_passwd'], db=conf['db_name'], port=conf['db_port']) as conn:
                async with conn.cursor() as cursor:
                    try:
                        await cursor.execute("SELECT userid, mcid FROM users;")
                        result = await cursor.fetchall()
                        for row in result:
                            if row[0] == message.author.id or row[1] == content:
                                await message.reply(f"{message.author.display_name}({message.author.name})または{content}はすでに登録されています")
                                return
                        await cursor.execute("INSERT INTO users (id, userid, mcid, plan) VALUES (NULL, %s, %s, %s);", (message.author.id, content, plan))
                        await conn.commit()
                    except aiomysql.MySQLError as e:
                        await conn.rollback()
                        await message.reply("内部エラーが発生しました\n再度お試しください")
                        await server.webhook("データベースエラー", e, False)
                        logger.error(e)
                        return
        except aiomysql.MySQLError as e:
            await message.reply("内部エラーが発生しました\n再度お試しください")
            await server.webhook("データベースエラー", e, False)
            logger.error(e)
            return

        r = await server.send_cmd(cmd)
        if not r:
            await message.reply("登録に失敗しました\nサポートにお問い合わせください")
            return
        await message.reply(f"{content} の登録が完了しました")
        await server.webhook(f"ユーザー登録完了", f"mcid: {content}\ndiscordの名前: {message.author.display_name}({message.author.name})\nプラン: {plan}", True)
        logger.success(f"MCID: {content}の登録処理が完了しました")
        return

scheduler.add_job(server.role_check, "interval", hours=1, args=[client])
try:
    client.run(token=conf['discord_token'])
except KeyboardInterrupt:
    scheduler.shutdown()
