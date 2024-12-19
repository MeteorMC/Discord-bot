import httpx
import discord
import aiomysql
import aiofiles
import json
import datetime
import asyncio
from loguru import logger
from datetime import datetime
from zoneinfo import ZoneInfo

async def send_cmd(CMD: str) -> bool:
    async with aiofiles.open("config.json", mode="r", encoding="utf-8") as f:
        conf = json.loads(await f.read())
    if not (conf['Token']['ServerPanel'] or conf['URL']['ServerPanel'] or conf['ID']['Server']):
        logger.critical("必要なデータがありません")
        return False
    async with httpx.AsyncClient() as client:
        headers = {
             "Accept": "application/json",
             "Authorization": f"Bearer {conf['Token']['ServerPanel']}",
             "Content-Type": "application/json"
        }
        try:
            r = await client.post(f"https://{conf['URL']['ServerPanel']}/api/client/servers/{conf['ID']['Server']}/command", headers=headers, json={"command": CMD})
        except httpx.RequestError as e:
            logger.error(f"予期せぬエラーが発生しました: {e}")
            return False
        if r.status_code != 204:
            logger.error(f"予期せぬステータスコード: {r.status_code}")
            return False
    return True

async def role_check(CLIENT: discord.Client) -> None:
    async with aiofiles.open("config.json", mode="r", encoding="utf-8") as f:
        conf = json.loads(await f.read())
    try:
         async with aiomysql.connect(host=conf['DB']['Host'], user=conf['DB']['User'], password=conf['DB']['Passwd'], db=conf['DB']['Name'], port=conf['DB']['Port']) as conn:
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute("SELECT userid, mcid, plan FROM users;")
                    result = await cursor.fetchall()
                    for row in result:
                        have_role = False
                        role_name = None
                        member = CLIENT.guilds[0].get_member(row[0])
                        if member:
                            for role in member.roles:
                                if role.id == conf['ID']['TargetRole1'] or role.id == conf['ID']['TargetRole2']:
                                    have_role = True
                                    role_name = role.name if role.name.islower() else role.name.lower()
                                    break
                            try:
                                if have_role and role_name != row[2]:
                                    await send_cmd(f"lp user {row[1]} parent remove {row[2]}")
                                    await send_cmd(f"lp user {row[1]} parent add {role_name}")
                                    await cursor.execute("UPDATE users SET plan = %s WHERE userid = %s AND mcid = %s AND plan = %s;", (role_name, row[0], row[1], row[2]))
                                    await conn.commit()
                                    logger.success(f"MCID: {row[1]}の加入プランを変更しました")
                                elif not have_role:
                                    await send_cmd(f"lp user {row[1]} parent remove {row[2]}")
                                    await cursor.execute("DELETE FROM users WHERE userid = %s AND mcid = %s AND plan = %s;", (row[0], row[1], row[2]))
                                    await conn.commit()
                                    await webhook("プラン解約のためユーザー削除完了", f"削除されたdiscord名: {member.display_name}({member.name})\nMCID: {row[1]}", conf['URL']['PrivateWebhook'], True)
                                    logger.success(f"MCID: {row[1]}の加入プランを解除しました")
                            except (TypeError, KeyError) as e:
                                await webhook("ユーザーのプランを変更しようとしたらエラーが発生しました", e, conf['URL']['PrivateWebhook'], False)
                                logger.error(f"ユーザーのプランを変更しようとしたらエラーが発生しました: {e}")
                                break
                        else:
                            await send_cmd(f"lp user {row[1]} parent remove {row[2]}")
                            await cursor.execute("DELETE FROM users WHERE userid = %s AND mcid = %s AND plan = %s;", (row[0], row[1], row[2]))
                            await conn.commit()
                            await webhook("サーバーにいないためユーザーを削除完了", f"MCID: {row[1]}", conf['URL']['PrivateWebhook'], True)
                            logger.success(f"MCID: {row[1]}はサーバーにいないため加入プランを解除します")
                except aiomysql.MySQLError as e:
                    await conn.rollback()
                    await webhook("データベースエラー", e, conf['URL']['PrivateWebhook'], False)
                    logger.error(e)
    except aiomysql.MySQLError as e:
        await webhook("データベースエラー", e, conf['URL']['PrivateWebhook'], False)
        logger.error(e)

async def webhook(TITLE: str, CONTENT: str, URL: str, SUCCESS: bool) -> None:
    async with httpx.AsyncClient() as client:
        data = {
            "username": "Meteor",
            "embeds": [
                {
                    "title": TITLE,
                    "description": CONTENT,
                    "timestamp": datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "color": 0x00FF00 if SUCCESS else 0xFF0000
                }
            ]
        }
        try:
            r = await client.post(URL, json=data, headers={"Content-Type": "application/json"})
        except httpx.RequestError as e:
            logger.error(f"予期せぬエラーが発生しました: {e}")
            return
    if r.status_code != 204:
        logger.warning(f"Webhook通知に失敗しました\nステータスコード: {r.status_code}")

async def crash_restart(CLIENT: discord.client) -> None:
    async with aiofiles.open("config.json", mode="r", encoding="utf-8") as f:
        conf = json.loads(await f.read())
    Bot = discord.utils.get(CLIENT.guilds).get_member(conf['ID']['WatcheBot'])
    if Bot.status == discord.Status.online and Bot.activity.type == discord.ActivityType.playing:
        BotStatus = Bot.activity.name.split('/')[0]
    else:
        BotStatus = 1

    async with httpx.AsyncClient() as client:
        headers = {
             "Accept": "application/json",
             "Authorization": f"Bearer {conf['Token']['ServerPanel']}"
        }
        r = await client.get(f"https://{conf['URL']['ServerPanel']}/api/client/servers/{conf['ID']['Server']}/resources", headers=headers)
        if r.status_code != 200:
            logger.error(f"予期せぬステータスコード: {r.status_code}")
            return
        content = r.json()['attributes']
        headers.update({"Authorization": f"Bearer {conf['Token']['ServerPanel']}", "Content-Type": "application/json"})
        if content['current_state'] == "running" and content['resources']['cpu_absolute'] < conf['Threshold']['Cpu'] and BotStatus > 0:
            r = await client.post(f"https://{conf['URL']['ServerPanel']}/api/client/servers/{conf['ID']['Server']}/power", headers=headers, json={"signal": "kill"})
            if r.status_code != 204:
                logger.error(f"予期せぬステータスコード: {r.status_code}")
                return
            await asyncio.sleep(1)
            r = await client.post(f"https://{conf['URL']['ServerPanel']}/api/client/servers/{conf['ID']['Server']}/power", headers=headers, json={"signal": "start"})
            if r.status_code != 204:
                logger.error(f"予期せぬステータスコード: {r.status_code}")
                return
            logger.success("再起動が完了しました")
            await webhook("再起動シグナル", "スレッドクラッシュが検知されたため再起動シグナルを送信しました", conf['URL']['PublicWebhook'], True)
        elif content['current_state'] == "starting" and content['resources']['cpu_absolute'] < 3:
            r = await client.post(f"https://{conf['URL']['ServerPanel']}/api/client/servers/{conf['ID']['Server']}/power", headers=headers, json={"signal": "kill"})
            if r.status_code != 204:
                logger.error(f"予期せぬステータスコード: {r.status_code}")
                return
            await asyncio.sleep(1)
            r = await client.post(f"https://{conf['URL']['ServerPanel']}/api/client/servers/{conf['ID']['Server']}/power", headers=headers, json={"signal": "start"})
            if r.status_code != 204:
                logger.error(f"予期せぬステータスコード: {r.status_code}")
                return
            await webhook("起動中にエラーが発生した可能性", "起動時にエラーが発生した可能性があるため、再起動シグナルを送信しました", conf['URL']['PublicWebhook'], True)
