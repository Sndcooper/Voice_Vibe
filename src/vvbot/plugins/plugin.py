# Vendored from n3d1117/chatgpt-telegram-bot @ df4dcaa26923dee560ef8f9b4f18a682c9b059ad
# (bot/plugins/plugin.py), GPL-2.0-only -- see src/vvbot/LICENSE. Unmodified apart from this header.
from abc import abstractmethod, ABC
from typing import Dict


class Plugin(ABC):
    """
    A plugin interface which can be used to create plugins for the ChatGPT API.
    """

    @abstractmethod
    def get_source_name(self) -> str:
        """
        Return the name of the source of the plugin.
        """
        pass

    @abstractmethod
    def get_spec(self) -> [Dict]:
        """
        Function specs in the form of JSON schema as specified in the OpenAI documentation:
        https://platform.openai.com/docs/api-reference/chat/create#chat/create-functions
        """
        pass

    @abstractmethod
    async def execute(self, function_name, helper, **kwargs) -> Dict:
        """
        Execute the plugin and return a JSON serializable response
        """
        pass
