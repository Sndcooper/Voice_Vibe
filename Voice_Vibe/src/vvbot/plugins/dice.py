# Vendored from n3d1117/chatgpt-telegram-bot @ df4dcaa26923dee560ef8f9b4f18a682c9b059ad
# (bot/plugins/dice.py), GPL-2.0-only -- see src/vvbot/LICENSE. Unmodified apart from this header.
from typing import Dict

from .plugin import Plugin


class DicePlugin(Plugin):
    """
    A plugin to send a die in the chat
    """
    def get_source_name(self) -> str:
        return "Dice"

    def get_spec(self) -> [Dict]:
        return [{
            "name": "send_dice",
            "description": "Send a dice in the chat, with a random number between 1 and 6",
            "parameters": {
                "type": "object",
                "properties": {
                    "emoji": {
                        "type": "string",
                        "enum": ["🎲", "🎯", "🏀", "⚽", "🎳", "🎰"],
                        "description": "Emoji on which the dice throw animation is based."
                                       "Dice can have values 1-6 for “🎲”, “🎯” and “🎳”, values 1-5 for “🏀” "
                                       "and “⚽”, and values 1-64 for “🎰”. Defaults to “🎲”.",
                    }
                },
            },
        }]

    async def execute(self, function_name, helper, **kwargs) -> Dict:
        return {
            'direct_result': {
                'kind': 'dice',
                'format': 'dice',
                'value': kwargs.get('emoji', '🎲')
            }
        }
