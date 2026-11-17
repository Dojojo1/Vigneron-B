"""The relay reads Discord fixtures and retries signed delivery without posting."""
import asyncio
from types import SimpleNamespace

from connectors.coffre_relay import CoffreRelay, CHANNEL_ID, FIRST_MESSAGE_ID, ALERT_CHANNEL_ID


def message(ident, *, action='depot', item='saleMoney', amount='10000000'):
    fields = {'sourceMessageId': f'{ident - 1}:0', 'eventTime': '2026-11-16T20:11:33+01:00',
              'action': action, 'itemId': item, 'amount': amount, 'playerCharacter': 'Profil test',
              'playerDiscord': '123'}
    return SimpleNamespace(id=ident, channel=SimpleNamespace(id=CHANNEL_ID),
                           author=SimpleNamespace(id=1490974768445390928, bot=True), embeds=[SimpleNamespace(
                               footer=SimpleNamespace(text='vinbot:coffre:v1'),
                               fields=[SimpleNamespace(name=k, value=f'`{v}`') for k, v in fields.items()],
                               url=f'https://discord.com/channels/932301610128912414/1219050172060008458/{ident - 1}')])


def test_relay_resumes_after_failed_delivery_and_does_not_repeat(tmp_path):
    messages = [message(FIRST_MESSAGE_ID), message(FIRST_MESSAGE_ID + 1)]

    class Channel:
        def history(self, *, after, oldest_first, limit):
            async def rows():
                for row in messages:
                    if row.id > after.id:
                        yield row
            return rows()

    class Website:
        def __init__(self): self.calls = []; self.fail = True
        async def event(self, kind, *, event_id, log):
            self.calls.append((kind, event_id, log))
            if self.fail and event_id == str(FIRST_MESSAGE_ID + 1):
                raise RuntimeError('Temporary failure')

    website = Website()
    bot = SimpleNamespace(get_channel=lambda ident: Channel())
    relay = CoffreRelay(bot, website, tmp_path / 'coffre.sqlite3')

    async def exercise():
        try:
            await relay.sync()
        except RuntimeError:
            pass
        else:
            raise AssertionError('Expected simulated failure')
        assert relay.cursor() == FIRST_MESSAGE_ID
        website.fail = False
        await CoffreRelay(bot, website, tmp_path / 'coffre.sqlite3').sync()
        assert relay.cursor() == FIRST_MESSAGE_ID + 1
        assert len(website.calls) == 3
        assert website.calls[0][2]['amount'] == 10000000
        assert await relay.sync() == 0

    asyncio.run(exercise())


def test_alert_only_for_new_proven_gap_with_fake_discord(tmp_path):
    class Channel:
        guild = SimpleNamespace(id=123)

        def __init__(self): self.messages = []; self.fail = False

        async def send(self, content):
            if self.fail: raise RuntimeError('Discord unavailable')
            self.messages.append(content)

    class Website:
        guild_id = '123'

        def __init__(self): self.snapshot = {'status': 'matched', 'issues': []}

        async def coffre_alert(self): return self.snapshot

    channel, website = Channel(), Website()
    requested = []
    def get_channel(ident):
        requested.append(ident)
        return channel
    bot = SimpleNamespace(get_channel=get_channel)
    path = tmp_path / 'coffre.sqlite3'
    relay = CoffreRelay(bot, website, path)
    issue = {'id': '1571966486782939269', 'delta': 1000000,
             'available': 900000, 'unexplained': 100000}

    async def exercise():
        assert await relay.alert_sync() is False
        assert not channel.messages
        website.snapshot = {'status': 'mismatch', 'startedAt': '2026-11-16T20:11:33+01:00',
                            'issues': [issue]}
        assert await relay.alert_sync() is False  # First observation is held for confirmation.
        channel.fail = True
        try: await relay.alert_sync()
        except RuntimeError: pass
        else: raise AssertionError('Failed send should retry')
        assert relay.alert_fingerprint() == ''
        channel.fail = False
        assert await relay.alert_sync() is True
        assert requested[-1] == ALERT_CHANNEL_ID
        assert '100,000 $' in channel.messages[0]
        assert await CoffreRelay(bot, website, path).alert_sync() is False
        assert len(channel.messages) == 1
        website.snapshot = {'status': 'unavailable', 'issues': []}
        assert await relay.alert_sync() is False
        website.snapshot = {'status': 'matched', 'issues': []}
        assert await relay.alert_sync() is False
        website.snapshot = {'status': 'mismatch', 'issues': [issue]}
        assert await relay.alert_sync() is False
        assert await relay.alert_sync() is True
        assert len(channel.messages) == 2

    asyncio.run(exercise())
