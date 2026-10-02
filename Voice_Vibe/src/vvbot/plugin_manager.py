# Derived from n3d1117/chatgpt-telegram-bot @ df4dcaa26923dee560ef8f9b4f18a682c9b059ad
# (bot/plugin_manager.py), GPL-2.0-only -- see src/vvbot/LICENSE.
# Modified for Voice Vibe: plugins are imported lazily and only when enabled
# (a missing optional dependency disables that plugin, rule 19), and only the
# dependency-free dice plugin is vendored so far. Upstream plugins were
# OpenAI function-calling tools; here the hub decides, so they are run
# explicitly with /run <function> [json].
import importlib
import json
import logging

# plugin name -> (module under vvbot.plugins, class name)
PLUGIN_MAPPING = {
    'dice': ('dice', 'DicePlugin'),
}


class PluginManager:
    """
    A class to manage the plugins and call the correct functions
    """

    def __init__(self, config):
        enabled_plugins = config.get('plugins', [])
        self.plugins = []
        for plugin in enabled_plugins:
            plugin = plugin.strip()
            if plugin not in PLUGIN_MAPPING:
                continue
            module_name, class_name = PLUGIN_MAPPING[plugin]
            try:
                module = importlib.import_module(f'vvbot.plugins.{module_name}')
                self.plugins.append(getattr(module, class_name)())
            except Exception as e:  # noqa: BLE001
                logging.warning(f'Plugin {plugin} not loaded: {e}')

    def get_functions_specs(self):
        """
        Return the list of function specs that can be called by the model
        """
        return [spec for specs in map(lambda plugin: plugin.get_spec(), self.plugins) for spec in specs]

    async def call_function(self, function_name, helper, arguments):
        """
        Call a function based on the name and parameters provided
        """
        plugin = self.__get_plugin_by_function_name(function_name)
        if not plugin:
            return json.dumps({'error': f'Function {function_name} not found'})
        return json.dumps(await plugin.execute(function_name, helper, **json.loads(arguments or '{}')), default=str)

    def get_plugin_source_name(self, function_name) -> str:
        """
        Return the source name of the plugin
        """
        plugin = self.__get_plugin_by_function_name(function_name)
        if not plugin:
            return ''
        return plugin.get_source_name()

    def __get_plugin_by_function_name(self, function_name):
        return next((plugin for plugin in self.plugins
                    if function_name in map(lambda spec: spec.get('name'), plugin.get_spec())), None)
