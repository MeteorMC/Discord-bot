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

if not conf['Token']['DiscordBot']:
    logger.critical("discord bot tokenがありません")
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")
client = discord.Client(intents=intents)

@client.event
async def setup_hook():
    logger.success("success")
    scheduler.start()

@client.event
async def on_message(message: discord.message.Message):
    if message.author.bot:
        return

    if message.channel.id == conf['ID']['TargetChannel']:
        content = message.content
        cmd = None
        join_player = None
        if len(content) >= 50:
            await message.reply("文字のしきい値が超えています\nサポートにお問い合わせください")
            logger.warning(f"最大文字数は50文字以内 || 文字数: {len(content)}")
            return

        async with httpx.AsyncClient() as client:
            try:
                r = await client.get(f"https://api.mojang.com/users/profiles/minecraft/{content}")
                if r.status_code != 200:
                    await message.reply(f"{content} は見つかりませんでした\n再度お試しください")
                    return
                headers = {
                    "Accept": "application/json",
                    "Authorization": f"Bearer {conf['Token']['ServerPanel']}"
                }
                r = await client.get(f"https://{conf['URL']['ServerPanel']}/api/client/servers/{conf['ID']['Server']}/resources", headers=headers)
                if r.json['attributes']['current_state'] != "running":
                    await message.reply("現在サーバーは起動していないため登録処理ができません\nしばらくたってから再度お試しください")
                    return
            except httpx.RequestError as e:
                await message.reply("内部エラーが発生しました\n再度お試しください")
                logger.error(e)
                return
        try:
            async with aiomysql.connect(host=conf['DB']['Host'], user=conf['DB']['User'], password=conf['DB']['Passwd'], db=conf['DB']['PlayerCheckName'], port=conf['DB']['Port']) as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT uuid FROM husksync_users;")
                    result = await cursor.fetchall()
                    for row in result:
                        if r.json()["id"] == row[0].replace("-", ""):
                            join_player = True
                            break
                    if not join_player:
                        await message.reply("一度もサーバーに参加していません\n参加してから再度お試しください")
                        logger.error(f"discord名: {message.author.display_name}({message.author.name})は一度もサーバーに参加していないため処理を停止")
                        return
        except (aiomysql.MySQLError, KeyError):
            logger.warning("サーバー参加プレイヤーチェックをスキップします")
        for role in message.author.roles:
            role_name = role.name if role.name.islower() else role.name.lower()
            if role.id == conf['ID']['TargetRole1'] or role.id == conf['ID']['TargetRole2']:
                cmd = f"lp user {r.json()["id"]} parent add {role_name}"
                break
        if not cmd:
            await message.reply("必要な情報がありません\nサポートにお問い合わせください")
            logger.error(f"discord名: {message.author.display_name}({message.author.name})には必要なロールがないため処理を停止")
            return

        try:
            async with aiomysql.connect(host=conf['DB']['Host'], user=conf['DB']['User'], password=conf['DB']['Passwd'], db=conf['DB']['Name'], port=conf['DB']['Port']) as conn:
                async with conn.cursor() as cursor:
                    try:
                        await cursor.execute("SELECT userid, mcid FROM users;")
                        result = await cursor.fetchall()
                        for row in result:
                            if row[0] == message.author.id or row[1] == content:
                                await message.reply(f"{message.author.display_name}({message.author.name})または{content}はすでに登録されています")
                                return
                        await cursor.execute("INSERT INTO users (id, userid, mcid, plan) VALUES (NULL, %s, %s, %s);", (message.author.id, r.json()["id"], role_name))
                        await conn.commit()
                    except aiomysql.MySQLError as e:
                        await conn.rollback()
                        await message.reply("内部エラーが発生しました\n再度お試しください")
                        await server.webhook("データベースエラー", e, conf['URL']['PrivateWebhook'], False)
                        logger.error(e)
                        return
        except aiomysql.MySQLError as e:
            await message.reply("内部エラーが発生しました\n再度お試しください")
            await server.webhook("データベースエラー", e, conf['URL']['PrivateWebhook'], False)
            logger.error(e)
            return

        r = await server.send_cmd(cmd)
        if not r:
            await message.reply("登録に失敗しました\nサポートにお問い合わせください")
            return
        await message.reply(f"{content} の登録が完了しました")
        await server.webhook(f"ユーザー登録完了", f"mcid: {content}\ndiscordの名前: {message.author.display_name}({message.author.name})\nプラン: {role_name}", conf['URL']['PrivateWebhook'], True)
        logger.success(f"MCID: {content}の登録処理が完了しました")
        return

scheduler.add_job(server.role_check, "interval", hours=1, args=[client])
scheduler.add_job(server.crash_restart, "interval", minutes=1, args=[client])
try:
    client.run(token=conf['Token']['DiscordBot'], log_level=40)
except KeyboardInterrupt:
    scheduler.shutdown()
