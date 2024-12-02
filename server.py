import httpx
import discord
import aiomysql
import aiofiles
import json
import datetime
from loguru import logger
from datetime import datetime
from zoneinfo import ZoneInfo

async def send_cmd(CMD: str) -> bool:
    async with aiofiles.open("config.json", mode="r", encoding="utf-8") as f:
        conf = json.loads(await f.read())
    if not (conf['server_token'] or conf['server_domain'] or conf['server_id']):
        logger.critical("必要なデータがありません")
        return False
    async with httpx.AsyncClient() as client:
        headers = {
             "Accept": "application/json",
             "Authorization": f"Bearer {conf['server_token']}",
             "Content-Type": "application/json"
        }
        try:
            r = await client.post(f"https://{conf['server_domain']}/api/client/servers/{conf['server_id']}/command", headers=headers, json={"command": CMD})
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
        async with aiomysql.connect(host=conf['db_host'], user=conf['db_user'], password=conf['db_passwd'], db=conf['db_name'], port=conf['db_port']) as conn:
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
                                if role.id == conf['target_role1'] or role.id == conf['target_role2']:
                                    have_role = True
                                    role_name = role.name if role.name.islower() else role.name.lower()
                                    break
                            try:
                                if have_role and role_name != row[2]:
                                    await send_cmd(f"lp user {row[1]} parent remove {row[2]}")
                                    await send_cmd(f"lp user {row[1]} parent add {role_name}")
                                    await cursor.execute("UPDATE users SET plan = %s WHERE userid = %s AND mcid = %s AND plan = %s;", (role_name, row[0], row[1], row[2]))
                                    await conn.commit()
                                    logger.success(f"MCID: {row[1]}の契約プランを変更しました")
                                elif not have_role:
                                    await send_cmd(f"lp user {row[1]} parent remove {row[2]}")
                                    await cursor.execute("DELETE FROM users WHERE userid = %s AND mcid = %s AND plan = %s;", (row[0], row[1], row[2]))
                                    await conn.commit()
                                    await webhook("プラン解約のためユーザー削除完了", f"削除されたdiscord名: {member.display_name}({member.name})\nMCID: {row[1]}", True)
                                    logger.success(f"MCID: {row[1]}の契約プランを解除しました")
                            except (TypeError, KeyError) as e:
                                await webhook("ユーザーのプランを変更しようとしたらエラーが発生しました", e, False)
                                logger.error(f"ユーザーのプランを変更しようとしたらエラーが発生しました: {e}")
                                break
                        else:
                            await send_cmd(f"lp user {row[1]} parent remove {row[2]}")
                            await cursor.execute("DELETE FROM users WHERE userid = %s AND mcid = %s AND plan = %s;", (row[0], row[1], row[2]))
                            await conn.commit()
                            await webhook("サーバーにいないためユーザーを削除完了", f"MCID: {row[1]}", True)
                            logger.success(f"MCID: {row[1]}はサーバーにいないため契約プランを解除します")
                except aiomysql.MySQLError as e:
                    await conn.rollback()
                    await webhook("データベースエラー", e, False)
                    logger.error(e)
    except aiomysql.MySQLError as e:
        await webhook("データベースエラー", e, False)
        logger.error(e)

async def webhook(TITLE: str, CONTENT: str, SUCCESS: bool) -> None:
    async with aiofiles.open("config.json", mode="r", encoding="utf-8") as f:
        conf = json.loads(await f.read())
    try:
        if not conf['webhook_url']:
            logger.warning("webhookは無効のため処理を停止")
            return
    except KeyError:
        logger.warning("webhookは無効のため処理を停止")
        return
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
            r = await client.post(conf['webhook_url'], json=data, headers={"Content-Type": "application/json"})
        except httpx.RequestError as e:
            logger.error(f"予期せぬエラーが発生しました: {e}")
            return
    if r.status_code != 204:
        logger.warning(f"Webhook通知に失敗しました\nステータスコード: {r.status_code}")
