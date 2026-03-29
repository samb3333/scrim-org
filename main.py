import discord
from discord import app_commands
import os
from dotenv import load_dotenv
from pathlib import Path
import json
import uuid
import requests
import datetime
import asyncio

load_dotenv()

teamsFile = 'teams.json'
orgFile = 'org.json'
scrimsFile = 'scrims.json'

guild_id = 1463609747109445634
guild=discord.Object(id=guild_id)

class MyClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.clear_commands(guild=guild)
        await self.tree.sync(guild=guild)

        await self.tree.sync()

client = MyClient()

@client.event
async def on_ready():
    client.loop.create_task(check_scrim())
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print('------')

# File functions
def loadFile(file, default=None):
    if default is None:
        default = {}
    with open(file, 'r') as f:
        if Path(file).stat().st_size == 0:
            return default
        tempdata = json.load(f)
        return tempdata

def saveFile(file, data):
    with open(file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def updateTeams(id, updates: dict):
    data = loadFile(teamsFile)

    data[str(id)] = updates

    saveFile(teamsFile, data)

def updateOrg(scrim_id, data: dict):
    all_data = loadFile(orgFile)
    existing = all_data.get(scrim_id, {})

    existing.update(data)
    all_data[scrim_id] = existing
    saveFile(orgFile, all_data)

def deleteOrg(scrim_id):
    data = loadFile(orgFile)

    if scrim_id in data:
        del data[scrim_id]
        saveFile(orgFile, data)
        return True
    return False

def deleteScrim(scrim_id):
    data = loadFile(scrimsFile)

    if scrim_id in data:
        del data[scrim_id]
        saveFile(scrimsFile, data)
        return True
    return False

def updateScrim(scrim_id, data:dict):
    all_data = loadFile(scrimsFile)
    existing = all_data.get(scrim_id, {})

    existing.update(data)
    all_data[scrim_id] = existing
    saveFile(scrimsFile, all_data)

# validation functions
def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message(
            'You must be an admin to use this command', ephemeral=True
        )

def getServers():
    API_KEY = os.getenv("OD")
    BASE_URL = "https://api.oriondrift.net/v2/fleets"

    params = {
        "include_config": "true",
        "include_stations": "true",
        "include_offline_fleets": "true",
        "page_size": 30,
        "page": 1
    }
    headers = {
        "x-api-key": f"{API_KEY}"
    }

    TARGET_REGIONS = {"eu-central-1"}
    TARGET_FLEETS = {"VRML Community", "ARES SHIP 4v4"}

    response = requests.get(BASE_URL, params=params, headers=headers)
    data = response.json()

    results = []

    for fleet in data["items"]:
        for station in fleet["stations"]:
            if station["region"] in TARGET_REGIONS:
                if fleet["fleet_name"] in TARGET_FLEETS:
                    if station['online'] == True and station['disabled'] == False:
                        results.append(station)

    results.sort(key=lambda s: s["player_count"])

    toReturn = []
    for a in results:
        toReturn.append(f"{a['station_name']} ({a['player_count']})")

    return toReturn

class ChooseServerView(discord.ui.View):
    def __init__(self, scrim_id: str):
        super().__init__(timeout=900)
        self.id = scrim_id
        servers = getServers()
        options = [discord.SelectOption(label=server, value=server) for server in servers]

        self.select = discord.ui.Select(options=options, placeholder='Select server to go to', min_values=1, max_values=1)
        self.select.callback = self.callback

        self.add_item(self.select)

    async def callback(self, interaction: discord.Interaction):
        selected = self.select.values
        for child in self.children:
            child.disabled = True   
        await interaction.response.edit_message(view=self)
        
        teams = loadFile(teamsFile)
        scrims = loadFile(scrimsFile)

        if self.id not in scrims:
            await interaction.followup.send("You're late! Try DM the captain... Not much I can do :)")
            self.stop()
            return

        await interaction.followup.send(f"Server: {selected[0]}")

        guild = client.get_guild(int(scrims[self.id]['away']))
        if guild is None:
            print("Guild error")
            return
        scrim_channel = guild.get_channel(teams[scrims[self.id]['away']]['scrim_channel'])
        if scrim_channel is None:
            print("Channel error")
            return
        permissions = scrim_channel.permissions_for(guild.me)

        if not permissions.send_messages:
            print(f"No permission to send in {scrim_channel} in {scrims[self.id]['away']}")
            return

        await scrim_channel.send(f"<@&{teams[scrims[self.id]['away']]['team_role']}> Server: {selected[0]}")

        deleteScrim(self.id)
        self.stop()

async def check_scrim():
    await client.wait_until_ready()
    while not client.is_closed():
        scrims = loadFile(scrimsFile)
        teams = loadFile(teamsFile)
        for id in scrims.keys():
            if timePassed(scrims[id]['time'], 15) == True and scrims[id]['server'] == False:
                guild = client.get_guild(int(scrims[id]['home']))
                if guild is None:
                    print("Guild error")
                    continue
                scrim_channel = guild.get_channel(teams[scrims[id]['home']]['scrim_channel'])
                if scrim_channel is None:
                    print("Channel error")
                    continue
                permissions = scrim_channel.permissions_for(guild.me)

                if not permissions.send_messages:
                    print(f"No permission to send in {scrim_channel} in {scrims[id]['home']}")
                    continue
                view = ChooseServerView(id)
                await scrim_channel.send(f"Select a server <@&{teams[scrims[id]['home']]['team_role']}>", view=view)
                updateScrim(id, {'server': True})
            elif timePassed(scrims[id]['time'], 0) == True:
                guild = client.get_guild(int(scrims[id]['home']))
                if guild is None:
                    print("Guild error")
                    continue
                scrim_channel = guild.get_channel(teams[scrims[id]['home']]['scrim_channel'])
                if scrim_channel is None:
                    print("Channel error")
                    continue
                permissions = scrim_channel.permissions_for(guild.me)

                if not permissions.send_messages:
                    print(f"No permission to send in {scrim_channel} in {scrims[id]['home']}")
                    continue
                await scrim_channel.send("Cancelling :(")

                guild = client.get_guild(int(scrims[id]['away']))
                if guild is None:
                    print("Guild error")
                    continue
                scrim_channel = guild.get_channel(teams[scrims[id]['away']]['scrim_channel'])
                if scrim_channel is None:
                    print("Channel error")
                    continue
                permissions = scrim_channel.permissions_for(guild.me)

                if not permissions.send_messages:
                    print(f"No permission to send in {scrim_channel} in {scrims[id]['home']}")
                    continue
                await scrim_channel.send("Cancelling :(")
                deleteScrim(id)
            elif timePassed(scrims[id]['time'], 5) == True and scrims[id]['reminded'] == False:
                guild = client.get_guild(int(scrims[id]['home']))
                if guild is None:
                    print("Guild error")
                    continue
                scrim_channel = guild.get_channel(teams[scrims[id]['home']]['scrim_channel'])
                if scrim_channel is None:
                    print("Channel error")
                    continue
                permissions = scrim_channel.permissions_for(guild.me)

                if not permissions.send_messages:
                    print(f"No permission to send in {scrim_channel} in {scrims[id]['home']}")
                    continue
                await scrim_channel.send(f"Select a server above ^^^ <@&{teams[scrims[id]['home']]['team_role']}>")

                guild = client.get_guild(int(scrims[id]['away']))
                if guild is None:
                    print("Guild error")
                    continue
                scrim_channel = guild.get_channel(teams[scrims[id]['away']]['scrim_channel'])
                if scrim_channel is None:
                    print("Channel error")
                    continue
                permissions = scrim_channel.permissions_for(guild.me)

                if not permissions.send_messages:
                    print(f"No permission to send in {scrim_channel} in {scrims[id]['away']}")
                    continue
                await scrim_channel.send(f"The other team isn't responding to set a server, try DM them or check ingame <@&{teams[scrims[id]['away']]['team_role']}>")
                updateScrim(id, {'reminded': True})

        org = loadFile(orgFile)
        for id in org.keys():
            if timePassed(org[id]['time'], 0) == True:
                guild = client.get_guild(int(org[id]['team']))
                if guild is None:
                    print("Guild error")
                    continue
                scrim_channel = guild.get_channel(teams[org[id]['team']]['scrim_channel'])
                if scrim_channel is None:
                    print("Channel error")
                    continue
                permissions = scrim_channel.permissions_for(guild.me)

                if not permissions.send_messages:
                    print(f"No permission to send in {scrim_channel} in {org[id]['team']}")
                    continue
                await scrim_channel.send(f"Cancelling, you didn't choose a team to vs :(")
                deleteOrg(id)
            elif timePassed(org[id]['time'], 15) == True and org[id].get('reminded', False) == False:
                guild = client.get_guild(int(org[id]['team']))
                if guild is None:
                    print("Guild error")
                    continue
                scrim_channel = guild.get_channel(teams[org[id]['team']]['scrim_channel'])
                if scrim_channel is None:
                    print("Channel error")
                    continue
                permissions = scrim_channel.permissions_for(guild.me)

                if not permissions.send_messages:
                    print(f"No permission to send in {scrim_channel} in {org[id]['team']}")
                    continue
                await scrim_channel.send(f"Select a team to vs <@&{teams[org[id]['team']]['team_role']}>")
                updateOrg(id, {'reminded': True})

        await asyncio.sleep(60)

def timePassed(time_str: str, offset: int) -> bool:
    try:
        hours, minutes = map(int, time_str.split(":"))
    except ValueError:
        return None
    
    now = datetime.datetime.now()
    target = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    target = target - datetime.timedelta(minutes=offset)

    if target <= now:
        return True
    return False

def timestamp(time_str: str, style="t") -> str | None:
    try:
        hours, minutes = map(int, time_str.split(":"))
    except ValueError:
        return None

    now = datetime.datetime.now()
    target = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)

    if target <= now:
        return None

    unix_ts = int(target.timestamp())
    return f"<t:{unix_ts}:{style}>"

class ChooseTeamView(discord.ui.View):
    def __init__(self, scrim_id: str, time:str):
        super().__init__(timeout=None)
        self.id = scrim_id
        self.msg = None

        self.time = time

        teams = loadFile(teamsFile)
        options = [discord.SelectOption(label=teams.get(str(team_id)).get('name'), value=team_id) for team_id in loadFile(orgFile).get(scrim_id).get('teams')]

        self.select = discord.ui.Select(options=options, placeholder='Choose the team to scrim', min_values=1, max_values=1)
        self.select.callback = self.callback

        self.add_item(self.select)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        selected = self.select.values
        if not selected:
            await interaction.followup.send('No team selected', ephemeral=True)
            return

        team_id = selected[0]
        org = loadFile(orgFile)
        team_data = org.get(self.id, {}).get('teams', {})

        if self.id not in org:
            for child in self.children:
                child.disabled = True
            await interaction.edit_original_response(view=self)
            return

        if team_data.get(team_id, {}).get('yes', 0) < 4:
            await interaction.followup.send('Team does not have enough players', ephemeral=True)
            # Reset the dropdown by editing with a fresh view
            new_view = ChooseTeamView(self.id, self.time)
            await interaction.edit_original_response(view=new_view)
            return

        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(view=self)

        teams = loadFile(teamsFile)
        await interaction.followup.send(f"Confirmed {teams[selected[0]]['name']} at {timestamp(self.time, "t")} {timestamp(self.time, "R")}\nYou will get a menu 15 mins before to select a server!")
  
        for id in team_data:
            if id == str(interaction.guild_id):
                continue
            guild = client.get_guild(int(id))
            if guild is None:
                continue
            scrim_channel = guild.get_channel(teams[id]['scrim_channel'])
            if scrim_channel is None:
                continue
            permissions = scrim_channel.permissions_for(guild.me)

            if not permissions.send_messages:
                print(f"No permission to send in {scrim_channel} in {id}")
                continue
            if id == team_id:
                await scrim_channel.send(f"<@&{teams[id]['team_role']}> Confirmed {teams[org.get(self.id, {}).get('team')]['name']} at {timestamp(self.time, "t")} {timestamp(self.time, "R")}")
            else:
                await scrim_channel.send("Scrim confirmed with a different team :(")

        updateScrim(self.id, {
            'time': self.time,
            'server': False,
            'reminded': False,
            'home': org.get(self.id, {}).get('team', "unknown"),
            'away': team_id
        })
        deleteOrg(self.id)

    async def refresh(self):
        await self.msg.edit(embed=self.get_message(), view=self)

    def get_message(self):        
        org = loadFile(orgFile).get(self.id).get('teams')
        teams = loadFile(teamsFile)

        message = ''
        for id in org:
            message += f"{teams.get(id).get('name')}:"
            message += " ".join(["✅"] * org.get(id).get('yes', 0))
            message += " ".join(["🤷‍♂️"] * org.get(id).get('maybe', 0))
            message += " ".join(["❌"] * org.get(id).get('no', 0))
            message += "\n"

        embed = discord.Embed(
            title=f"Scrim at {timestamp(self.time, "t")} {timestamp(self.time, "R")}",
            description=message,
            color=discord.Color.blue()
        )
        return embed
  
class YesMaybeNoView(discord.ui.View):
    def __init__(self, scrim_id: str, time:str, team: str, refreshView=None):
        super().__init__(timeout=None)
        self.id = scrim_id
        self.refreshView = refreshView
        
        org = loadFile(orgFile)

        self.team = team
        self.time = time

        self.yes_users = org.get(scrim_id, {}).get(team, {}).get('yes', [])
        self.maybe_users = org.get(scrim_id, {}).get(team, {}).get('maybe', [])
        self.no_users = org.get(scrim_id, {}).get(team, {}).get('no', [])

        yes_button = discord.ui.Button(label='Yes', style=discord.ButtonStyle.green, custom_id=f'yes_{scrim_id}{team}')
        maybe_button = discord.ui.Button(label='Maybe', style=discord.ButtonStyle.gray, custom_id=f'maybe_{scrim_id}{team}')
        no_button = discord.ui.Button(label='No', style=discord.ButtonStyle.red, custom_id=f'no_{scrim_id}{team}')

        yes_button.callback = self.yes
        maybe_button.callback = self.maybe
        no_button.callback = self.no

        self.add_item(yes_button)
        self.add_item(maybe_button)
        self.add_item(no_button)

    async def yes(self, interaction: discord.Interaction):
        org = loadFile(orgFile)
        if self.id not in org:
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(view=self)
            self.stop()
            return
        
        if interaction.user.id in self.yes_users:
            await interaction.response.send_message(content='Already set to yes', ephemeral=True)
            return
        self.yes_users.append(interaction.user.id)
        self.maybe_users.remove(interaction.user.id) if interaction.user.id in self.maybe_users else None
        self.no_users.remove(interaction.user.id) if interaction.user.id in self.no_users else None
        await interaction.message.edit(embed=self.get_message(), view=self)
        await interaction.response.send_message(content='Set to yes', ephemeral=True)
        if self.refreshView:
            await self.refreshView.refresh()

    async def maybe(self, interaction: discord.Interaction):
        org = loadFile(orgFile)
        if self.id not in org:
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(view=self)
            self.stop()
            return
        
        if interaction.user.id in self.maybe_users:
            await interaction.response.send_message(content='Already set to maybe', ephemeral=True)
            return
        self.maybe_users.append(interaction.user.id)
        self.yes_users.remove(interaction.user.id) if interaction.user.id in self.yes_users else None
        self.no_users.remove(interaction.user.id) if interaction.user.id in self.no_users else None
        await interaction.message.edit(embed=self.get_message(), view=self)
        await interaction.response.send_message(content='Set to maybe', ephemeral=True)
        if self.refreshView:
            await self.refreshView.refresh()

    async def no(self, interaction: discord.Interaction):
        org = loadFile(orgFile)
        if self.id not in org:
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(view=self)
            self.stop()
            return
        
        if interaction.user.id in self.no_users:
            await interaction.response.send_message(content='Already set to no', ephemeral=True)
            return
        self.no_users.append(interaction.user.id)
        self.yes_users.remove(interaction.user.id) if interaction.user.id in self.yes_users else None
        self.maybe_users.remove(interaction.user.id) if interaction.user.id in self.maybe_users else None
        await interaction.message.edit(embed=self.get_message(), view=self)
        await interaction.response.send_message(content='Set to no', ephemeral=True)
        if self.refreshView:
            await self.refreshView.refresh()

    def get_message(self):
        org = loadFile(orgFile)
        teamsData = org.get(self.id, {}).get('teams', {})
        teamsData[self.team] = {
                    'yes': len(self.yes_users),
                    'maybe': len(self.maybe_users),
                    'no': len(self.no_users)
                }
        updateOrg(self.id, {'teams': teamsData})

        message = ''
        message += '✅: ' + ', '.join(f'<@{uid}>' for uid in self.yes_users) + '\n'
        message += '🤷‍♂️: ' + ', '.join(f'<@{uid}>' for uid in self.maybe_users) + '\n'
        message += '❌: ' + ', '.join(f'<@{uid}>' for uid in self.no_users) + '\n'

        org = loadFile(orgFile)
        requester = loadFile(teamsFile).get(org.get(self.id).get('team')).get('name')
        embed = discord.Embed(
                title=f"Scrim vs {requester} at {timestamp(self.time, "t")} {timestamp(self.time, "R")}",
                description=message,
                color=discord.Color.blue()
            )
        return embed

class TeamChoiceView(discord.ui.View):
    def __init__(self, time: str):
        super().__init__(timeout=60)
        self.time = time

        options = [discord.SelectOption(label=team['name'], value=team_id) for team_id, team in loadFile(teamsFile).items()]

        self.select = discord.ui.Select(options=options, placeholder='Select teams to send scrim to', min_values=1, max_values=len(options))
        self.select.callback = self.callback

        self.add_item(self.select)

    async def callback(self, interaction: discord.Interaction):
        selected = [
            id for id in self.select.values
            if str(id) != str(interaction.guild.id)
        ]

        if not selected:
            await interaction.followup.send(
                "You can't scrim your own team 😭",
                ephemeral=True
            )
            return

        for child in self.children:
                child.disabled = True
        await interaction.response.edit_message(view=self)
        
        scrim_id = str(uuid.uuid4())
        teamsData = loadFile(orgFile).get(scrim_id, {}).get('teams', {})
        for id in selected:
            if str(id) != str(interaction.guild.id):
                teamsData[id] = {
                        'yes': 0,
                        'maybe': 0,
                        'no': 0
                    }

        updateOrg(scrim_id, {
            'team': str(interaction.guild.id),
            'time': self.time,
            'reminded': False,
            'teams': teamsData
            })
        
        refreshView = ChooseTeamView(str(scrim_id), self.time)
        teams = loadFile(teamsFile)

        for id in selected:
            if id == str(interaction.guild_id):
                continue
            guild = client.get_guild(int(id))
            if guild is None:
                continue
            scrim_channel = guild.get_channel(teams[id]['scrim_channel'])
            if scrim_channel is None:
                continue
            permissions = scrim_channel.permissions_for(guild.me)

            if not permissions.send_messages:
                print(f"No permission to send in {scrim_channel} in {id}")
                continue
            view = YesMaybeNoView(str(scrim_id), self.time, str(id), refreshView)
            await scrim_channel.send(content=f"<@&{teams[id]['team_role']}>", embed=view.get_message(), view=view)

        msg = await interaction.channel.send(
            content=f"<@&{teams[str(interaction.guild.id)]['team_role']}>", embed=refreshView.get_message(), view=refreshView
        )
        refreshView.msg = msg

@client.tree.command(name='scrim', description='Setup a scrim')
@discord.app_commands.describe(time='Time (18:00)')
async def scrim(interaction: discord.Interaction, time: str):
    teams = loadFile(teamsFile)
    if str(interaction.guild_id) not in teams:
        await interaction.response.send_message('Use /setup', ephemeral=True)
        return
    
    scrimChannelID = teams[str(interaction.guild_id)]['scrim_channel']
    if interaction.channel_id != scrimChannelID:
        await interaction.response.send_message(f'Go to <#{scrimChannelID}>', ephemeral=True)
        return
    
    try:
        hours, minutes = map(int, time.split(":"))
        if not (0 <= hours < 24 and 0 <= minutes < 60):
            raise ValueError
    except ValueError:
        await interaction.response.send_message(
            "Invalid time format. Use HH:MM (24h).",
            ephemeral=True
        )
        return
    if timePassed(time, 15) == True:
        await interaction.response.send_message("Makes scrims >15 mins away >:(", ephemeral=True)
        return
    view = TeamChoiceView(time)
    await interaction.response.send_message('Select teams to send scrim to', view=view ,ephemeral=True)

@is_admin()
@client.tree.command(name='setup', description='Setup the bot in your server')
@discord.app_commands.describe(team='Team name', scrim_channel='Private channel for scrims', team_role='Role for team members')
async def setup(interaction: discord.Interaction, team: str, scrim_channel: discord.TextChannel, team_role: discord.Role):
    teams = loadFile(teamsFile)
    for key in teams.keys():
        if teams[key]['name'] == team and key != str(interaction.guild.id):
            await interaction.response.send_message(f"{team} already used! Use other name", ephemeral=True)
            return
    updateTeams(interaction.guild_id, {
        'name': team,
        'scrim_channel': scrim_channel.id,
        'team_role': team_role.id
    })
    await interaction.response.send_message(f'Setup complete for {team}! Give me the team role or make sure I can view <#{scrim_channel.id}>', ephemeral=True)

client.run(os.getenv('DISCORD_TOKEN'))