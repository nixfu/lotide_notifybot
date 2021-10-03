#!/usr/bin/python3 -u

# =============================================================================
# IMPORTS
# =============================================================================
import re
import configparser
import logging
import logging.handlers
import time
import os
import sys
from enum import Enum
import operator
import random
import yaml
import re
import requests
import sqlite3
import pprint
import ssl
from datetime import datetime
import dateutil.parser as dp
pp = pprint.PrettyPrinter(indent=4)
import json
sys.path.append("%s/github/bots/userdata" % os.getenv("HOME"))
from requests.exceptions import HTTPError
from discord_webhook import DiscordWebhook, DiscordEmbed

from lxml import html
from lxml.html.clean import clean_html


# =============================================================================
# GLOBALS
# =============================================================================
# Reads the config file
config = configparser.ConfigParser()
config.read("bot.cfg")
config.read("auth.cfg")

Settings = {}
Settings = {s: dict(config.items(s)) for s in config.sections()}

ENVIRONMENT = config.get("BOT", "environment")
DEV_USER_NAME = config.get("BOT", "dev_user")
RUNNING_FILE = "bot.pid"

if Settings['Config']['loglevel'] == "debug":
    LOG_LEVEL = logging.DEBUG
else:
    LOG_LEVEL = logging.INFO
LOG_FILENAME = Settings['Config']['logfile']
LOG_FILE_INTERVAL = 2
LOG_FILE_BACKUPCOUNT = 5
LOG_FILE_MAXSIZE = 5000 * 256

logger = logging.getLogger('bot')
logger.setLevel(LOG_LEVEL)
log_formatter = logging.Formatter('%(levelname)-8s:%(asctime)s:%(lineno)4d - %(message)s')
log_stderrHandler = logging.StreamHandler()
log_stderrHandler.setFormatter(log_formatter)
logger.addHandler(log_stderrHandler)
if LOG_FILENAME:
    log_fileHandler = logging.handlers.TimedRotatingFileHandler(LOG_FILENAME, when='d', interval=LOG_FILE_INTERVAL, backupCount=LOG_FILE_BACKUPCOUNT) 
    log_fileHandler.setFormatter(log_formatter)
    logger.addHandler(log_fileHandler)
logger.propagate = False

os.environ['TZ'] = 'US/Eastern'


# =============================================================================
# FUNCTIONS
# =============================================================================
def create_running_file():
    # creates a file that exists while the process is running
    running_file = open(RUNNING_FILE, "w")
    running_file.write(str(os.getpid()))
    running_file.close()


def create_db():
    # create database tables if don't already exist
    try:
        con = sqlite3.connect(Settings['Config']['dbfile'])
        ccur = con.cursor()
        ccur.execute("CREATE TABLE IF NOT EXISTS processed (id TEXT, epoch INTEGER)")
        con.commit
    except sqlite3.Error as e:
        logger.error("Error2 {}:".format(e.args[0]))
        sys.exit(1)
    finally:
        if con:
            con.close()

def check_processed_sql(messageid):
    logging.debug("Check processed for id=%s" % messageid)
    try:
        con = sqlite3.connect(Settings['Config']['dbfile'])
        qcur = con.cursor()
        qcur.execute('''SELECT id FROM processed WHERE id=?''', (messageid,))
        row = qcur.fetchone()
        if row:
            return True
        else:
            return False
    except sqlite3.Error as e:
        logger.error("Error2 {}:".format(e.args[0]))
        sys.exit(1)
    finally:
        if con:
            con.close()


def save_processed_sql(messageid):
    logging.debug("Save processed for id=%s" % messageid)
    try:
        con = sqlite3.connect(Settings['Config']['dbfile'])
        qcur = con.cursor()
        qcur.execute('''SELECT id FROM processed WHERE id=?''', (messageid,))
        row = qcur.fetchone()
        if row:
            return True
        else:
            icur = con.cursor()
            insert_time = int(round(time.time()))
            icur.execute("INSERT INTO processed VALUES(?, ?)",
                         [messageid, insert_time])
            con.commit()
            return False
    except sqlite3.Error as e:
        logger.error("SQL Error:" % e)
    finally:
        if con:
            con.close()

def process_lotide_post(post,lotideToken):
    id = post['id']
    title = post['title']
    author_name = post['author']['username']
    author_url = post['author']['remote_url']
    created = post['created']
    community_name = post['community']['name']
    community_url = post['community']['remote_url']
    score = post['score']
    community_local = post['community']['local']
    created_sec = int(dp.parse(created).timestamp())
    post_url = Settings['hitide']['hitideurl'] + "/posts/" + str(id)

    if 'content_url' in post and post['content_html']:
        content_html = post['content_html']
        htmltree = html.fromstring(content_html)
        content_totext = clean_html(htmltree).text_content().strip()
    else:
        content_totext = ""


    # skip posts older than maxage_secs
    curtime = int(time.time())
    post_age = curtime - created_sec
    if post_age > int(Settings['Config']['maxage_secs']):
        return

    # skip posts by skipusers
    if 'skipusers' in Settings['Config'] and author_name.lower() in Settings['Config']['skipusers'].lower():
        return
    # skip non-local communities
    if not community_local:
        return
    # skip posts in skipcommunities
    if 'skipcommunities' in Settings['Config'] and community_name.lower() in Settings['Config']['skipcommunities'].lower():
        return
    # if allowedcommunities defined, skip posts not in allowedcommunities
    if 'allowedcommunities' in Settings['Config'] and not community_name.lower() in Settings['Config']['allowedcommunities'].lower():
        return

    logger.info("%-20s: process post: %s AGE=%s SCORE=%s author=%s %s %s" % (community_name, time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(created_sec)), post_age, score, author_name, title, post_url))

    try: 
        discordWebHook = DiscordWebhook(url=Settings['discord']['discordurl'], username="HootBot", content="Go checkout this new post on Hoot: " + Settings['hoot']['hooturl'] + "/communities", rate_limit_retry=True)
        embed = DiscordEmbed(title=title, color='8600DD', description=content_totext)
        embed.set_url(post_url)
        embed.set_author(name=author_name)
        embed.set_footer(text="Community: " + community_name)
        embed.set_timestamp()
        with open("hoot.png", "rb") as f:
           discordWebHook.add_file(file=f.read(), filename='hoot.png')
        embed.set_thumbnail(url='attachment://hoot.png')
        discordWebHook.add_embed(embed)
        response = discordWebHook.execute()

        save_processed_sql(id)
       
    except HTTPError as http_err:
       print(f'HTTP error occurred: {http_err}')
       return
    except Exception as err:
       print(f'Other error occurred: {err}')
       return
        
def getLotideToken():
    newToken = ""
    logindata = {
            "username": Settings['lotide']['username'],
            "password": Settings['lotide']['password']
    }

    loginheaders = {
        'content-type': "application/json",
        'cache-control': "no-cache",
    }
    lotideURL = Settings['lotide']['lotideurl'] + "/api/unstable/logins"

    try:
        loginResponse = requests.post(lotideURL, data=json.dumps(logindata), headers=loginheaders)
        if loginResponse.status_code == 200:
            loginResponse.encoding = 'utf-8'
            loginJSON = loginResponse.json()
            if 'token' in loginJSON:
                return loginJSON['token']
    except HTTPError as http_err:
            print(f'HTTP error occurred: {http_err}')
    except Exception as err:
            print(f'Other error occurred: {err}')
    

# =============================================================================
# MAIN
# =============================================================================


def main():
    start_process = False
    logger.info("start program")

    # create db tables if needed
    logger.debug("Create DB tables if needed")
    create_db()

    if ENVIRONMENT == "DEV" and os.path.isfile(RUNNING_FILE):
        os.remove(RUNNING_FILE)
        logger.debug("DEV=running file removed")

    if not os.path.isfile(RUNNING_FILE):
        create_running_file()
        start_process = True
    else:
        logger.error("bot already running! Will not start.")

    # Initalize
    next_refresh_time = 0
    subList = []
    subList_prev = []
    lotideToken = ""

    while start_process and os.path.isfile(RUNNING_FILE):
        logger.debug("Start Main Loop")

        # setup lotide session
        if not lotideToken:
            lotideToken = getLotideToken()
        logger.debug("Lotide Token: %s" % lotideToken)

        # get list of new lotide posts
        lotideHeaders =  {
            'authorization': "Bearer " + lotideToken,
            'content-type': "application/json",
            'cache-control': "no-cache",
        }

        try:
             page = 1
             next_page = ""
             while page <= 5: 
                 if next_page:
                    requestpage = "&page=%s" % next_page
                 else:
                    requestpage = ""
                 lotideResult = requests.get(Settings['lotide']['lotideurl']+"/api/unstable/posts?limit=100"+requestpage, headers=lotideHeaders)
                 lotideJson = lotideResult.json()

                 if 'next_page' in lotideJson and lotideJson['next_page']:
                     next_page = lotideJson['next_page']
                 else:
                     next_page = ""
                 for post in lotideJson['items']:
                     if check_processed_sql(post['id']):
                         continue
                     else:
                         process_lotide_post(post, lotideHeaders)
                 page += 1
             
        except HTTPError as http_err:
             print(f'HTTP error occurred: {http_err}')
        except Exception as err:
             print(f'Other error occurred: {err}')

        # Allows the bot to exit on ^C, all other exceptions are ignored
        except KeyboardInterrupt:
            break
        except Exception as err:
            logger.exception("Unknown Exception in Main Loop")

        logger.debug("End Main Loop - Pause %s secs" % Settings['Config']['main_loop_pause_secs'])
        time.sleep(int(Settings['Config']['main_loop_pause_secs']))

    logger.info("end program")
    sys.exit()


# =============================================================================
# RUNNER
# =============================================================================

if __name__ == '__main__':
    main()
