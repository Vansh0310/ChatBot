import slack
import os
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, Response, jsonify
from slackeventsapi import SlackEventAdapter
import string
from datetime import datetime, timedelta
from transformers import GPT2LMHeadModel, GPT2Tokenizer,GPT2Model
import torch
import logging
from transformers import pipeline
from groq import Groq

print(torch.__version__)

pipe = pipeline("text-generation", model="openai-community/gpt2")

env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

tokenizer = GPT2Tokenizer.from_pretrained('gpt2')
model = GPT2Model.from_pretrained('gpt2')


app = Flask(__name__)
slack_event_adapter = SlackEventAdapter(
    os.environ['SIGNING_SECRET'], '/slack/events', app)
print(os.environ['SIGNING_SECRET'])

client = slack.WebClient(token=os.environ['SLACK_TOKEN'])
BOT_ID = client.api_call("auth.test")['user_id']

Grok_client = Groq(
    api_key=os.environ.get("GROQ_API_KEY"),
)


message_counts = {}
welcome_messages = {}

BAD_WORDS = ['hmm', 'no', 'tim']

SCHEDULED_MESSAGES = [
    {'text': 'First message', 'post_at': (
        datetime.now() + timedelta(seconds=20)).timestamp(), 'channel': 'C01BXQNT598'},
    {'text': 'Second Message!', 'post_at': (
        datetime.now() + timedelta(seconds=30)).timestamp(), 'channel': 'C01BXQNT598'}
]

class WelcomeMessage:
    START_TEXT = {
        'type': 'section',
        'text': {
            'type': 'mrkdwn',
            'text': (
                'Welcome to this awesome channel! \n\n'
                '*Get started by completing the tasks!*'
            )
        }
    }

    DIVIDER = {'type': 'divider'}

    def __init__(self, channel):
        self.channel = channel
        self.icon_emoji = ':robot_face:'
        self.timestamp = ''
        self.completed = False

    def get_message(self):
        return {
            'ts': self.timestamp,
            'channel': self.channel,
            'username': 'Welcome Robot!',
            'icon_emoji': self.icon_emoji,
            'blocks': [
                self.START_TEXT,
                self.DIVIDER,
                self._get_reaction_task(),
                self._get_action_buttons()
            ]
        }

    def _get_reaction_task(self):
        checkmark = ':white_check_mark:'
        if not self.completed:
            checkmark = ':white_large_square:'

        text = f'{checkmark} *React to this message!*'

        return {'type': 'section', 'text': {'type': 'mrkdwn', 'text': text}}

    def _get_action_buttons(self):
        return {
            'type': 'actions',
            'elements': [
                {
                    'type': 'button',
                    'text': {'type': 'plain_text', 'text': 'Complete Task'},
                    'action_id': 'complete_task'
                }
            ]
        }

def send_welcome_message(channel, user):
    if channel not in welcome_messages:
        welcome_messages[channel] = {}

    if user in welcome_messages[channel]:
        return

    welcome = WelcomeMessage(channel)
    message = welcome.get_message()

    welcome_messages[channel][user] = welcome



def check_if_bad_words(message):
    msg = message.lower()
    msg = msg.translate(str.maketrans('', '', string.punctuation))

    return any(word in msg for word in BAD_WORDS)




@slack_event_adapter.on('message')
def message(payload):
    event = payload.get('event', {})
    channel_id = event.get('channel')
    user_id = event.get('user')
    text = event.get('text')

    # Ignore messages sent by the bot itself
    if user_id == BOT_ID:
        return Response(), 200

    try:
        chat_completion = Grok_client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": text,
                }
            ],
            model="llama3-8b-8192",
            stream= False
        )
        result = chat_completion.choices[0].message.content
        client.chat_postMessage(channel=channel_id, text=result)
    except Exception as e:
        print(f"Error: {e}")
    return Response(), 200


@slack_event_adapter.on('reaction_added')
def reaction(payload):
    event = payload.get('event', {})
    channel_id = event.get('item', {}).get('channel')
    user_id = event.get('user')

    if f'@{user_id}' not in welcome_messages:
        return

    welcome = welcome_messages[f'@{user_id}'][user_id]
    welcome.completed = True
    welcome.channel = channel_id
    message = welcome.get_message() 
    updated_message = client.chat_update(**message)
    welcome.timestamp = updated_message['ts']

@app.route('/slack/interactions', methods=['POST'])
def interactions():
    payload = request.json
    action = payload.get('actions', [])[0]
    action_id = action.get('action_id')

    if action_id == 'complete_task':
        user_id = payload.get('user', {}).get('id')
        channel_id = payload.get('channel', {}).get('id')

        if f'@{user_id}' in welcome_messages:
            welcome = welcome_messages[f'@{user_id}'][user_id]
            welcome.completed = True
            message = welcome.get_message()
            client.chat_update(**message)

        client.chat_postMessage(
            channel=channel_id, text=f"<@{user_id}> has completed the task!")
    
    return Response(), 200

@app.route('/message-count', methods=['POST'])
def message_count():
    data = request.form
    user_id = data.get('user_id')
    channel_id = data.get('channel_id')
    message_count = message_counts.get(user_id, 0)

    client.chat_postMessage(
        channel=channel_id, text=f"Message: {message_count}")
    return Response(), 200

if __name__ == "__main__":
    app.run(debug=True)
