"""Read-only Discord coffre mirror -> signed site events, with a durable cursor.

This module is copied into the existing bot. It never sends a Discord message.
"""
import asyncio
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


CHANNEL_ID = 1567451843838083082
AUTHOR_ID = 1490974768445390928
FIRST_MESSAGE_ID = 1571966270356856975  # Deposit of 10 M saleMoney.
FIRST_EVENT = datetime.fromisoformat('2026-11-16T20:11:33+01:00').timestamp()
FOOTER = 'vinbot:coffre:v1'


class CoffreRelay:
    def __init__(self, bot, website, path):
        self.bot, self.website, self.path = bot, website, Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS cursor(id INTEGER PRIMARY KEY CHECK(id=1),message_id TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO cursor VALUES(1,?)', (str(FIRST_MESSAGE_ID - 1),))
        self.path.chmod(0o600)
        self.task = None

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def cursor(self):
        with self.connect() as db:
            return int(db.execute('SELECT message_id FROM cursor WHERE id=1').fetchone()[0])

    def advance(self, message_id):
        with self.connect() as db:
            db.execute('UPDATE cursor SET message_id=? WHERE id=1 AND CAST(message_id AS INTEGER)<?',
                       (str(message_id), int(message_id)))

    @staticmethod
    def log(message):
        if (int(message.channel.id) != CHANNEL_ID or int(message.author.id) != AUTHOR_ID
                or not message.author.bot or not message.embeds):
            return None
        embed = message.embeds[0]
        if not embed.footer or not str(embed.footer.text or '').startswith(FOOTER):
            return None
        fields = {field.name: field.value.strip(chr(96)) for field in embed.fields}
        required = ('sourceMessageId', 'eventTime', 'action', 'itemId', 'amount', 'playerCharacter')
        if any(not fields.get(key) for key in required):
            raise ValueError('Log du coffre incomplet.')
        when = datetime.fromisoformat(fields['eventTime'])
        if when.tzinfo is None:
            raise ValueError('Date du coffre sans fuseau horaire.')
        if when.timestamp() < FIRST_EVENT:
            return None
        return {'channelId': str(CHANNEL_ID), 'messageId': str(message.id),
                'sourceMessageId': fields['sourceMessageId'], 'eventTime': fields['eventTime'],
                'action': fields['action'], 'itemId': fields['itemId'], 'amount': int(fields['amount']),
                'playerName': fields['playerCharacter'], 'playerDiscord': fields.get('playerDiscord'),
                'sourceUrl': embed.url}

    async def sync(self):
        channel = self.bot.get_channel(CHANNEL_ID) or await self.bot.fetch_channel(CHANNEL_ID)
        sent = 0
        for _ in range(20):
            seen = 0
            async for message in channel.history(after=SimpleNamespace(id=self.cursor()),
                                                 oldest_first=True, limit=100):
                seen += 1
                payload = self.log(message)
                if payload is not None:
                    await self.website.event('coffre_log', event_id=str(message.id), log=payload)
                    sent += 1
                self.advance(message.id)
            if seen < 100:
                break
        return sent

    async def run(self):
        while True:
            try:
                await self.sync()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                print(f'[SITE COFFRE] Lecture ou livraison différée ({type(error).__name__}).', flush=True)
            await asyncio.sleep(60)

    async def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run(), name='website-coffre')

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
