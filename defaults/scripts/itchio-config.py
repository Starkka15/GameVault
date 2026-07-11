#!/usr/bin/env python
import itchio
import json
import argparse
import os

import GameSet


class ItchioArgs(GameSet.GenericArgs):
    def __init__(self, storeName, setNameConfig):
        super().__init__()
        self.addArguments()
        self.setNameConfig = setNameConfig
        self.storeName = storeName

    def addArguments(self):
        super().addArguments()
        self.parser.add_argument(
            '--list', help='Get list of itch.io games', action='store_true')
        self.parser.add_argument(
            '--get-game-dir', help='Get install directory for game')
        self.parser.add_argument(
            '--getprogress', help='Get installation progress for game')
        self.parser.add_argument(
            '--get-args', help='Get game arguments')
        self.parser.add_argument(
            '--launchoptions', nargs=3, help='Get launch options')
        self.parser.add_argument(
            '--getloginstatus', help='Get login status', action='store_true')
        self.parser.add_argument(
            '--get-base64-images', help='Get base64 images for short name'
        )
        self.parser.add_argument(
            '--offline', help='Offline mode', action='store_true')
        self.parser.add_argument(
            '--update-game-details', help='Update game details')
        self.parser.add_argument(
            '--get-game-size', nargs=2, help='Get game size')
        self.parser.add_argument(
            '--flush-cache', help='Flush cache', action='store_true')
        self.parser.add_argument(
            '--download-game', help='Download game from itch.io')
        self.parser.add_argument(
            '--install-dir', help='Install directory for downloads')
        self.parser.add_argument(
            '--detect-executable', help='Detect executable in installed game directory')
        self.parser.add_argument(
            '--browse-games', nargs='*', help='Browse/search itch.io games')
        self.parser.add_argument(
            '--add-browse-to-library', help='Add a browsed game to local library by game ID')
        self.parser.add_argument(
            '--get-browse-details', help='Get details for a browsed game by ID')
        self.parser.add_argument(
            '--get-collections', help='List the user\'s itch.io collections', action='store_true')
        self.parser.add_argument(
            '--get-itch-tabs', help='Owned + per-collection sub-tabs (StoreTabs)', action='store_true')

    def parseArgs(self):
        super().parseArgs()
        self.gameSet = itchio.Itchio(self.args.dbfile, self.storeName, self.setNameConfig)
        self.gameSet.create_tables()

    def processArgs(self):
        try:
            super().processArgs()

            if self.args.list:
                print(self.gameSet.get_list(self.args.offline))
            if self.args.get_game_dir:
                self.gameSet.get_game_dir(
                    self.args.get_game_dir)
            if self.args.getprogress:
                print(self.gameSet.get_last_progress_update(
                    self.args.getprogress))
            if self.args.get_args:
                conn = self.gameSet.get_connection()
                c = conn.cursor()
                c.execute("SELECT Arguments FROM Game WHERE ShortName=?", (self.args.get_args,))
                result = c.fetchone()
                conn.close()
                print(result[0] if result and result[0] else "")
            if self.args.launchoptions:
                print(self.gameSet.get_lauch_options(
                    self.args.launchoptions[0], self.args.launchoptions[1], self.args.launchoptions[2], self.args.offline))

            if self.args.getloginstatus:
                print(self.gameSet.get_login_status(self.args.flush_cache))

            if self.args.get_base64_images:
                print(self.gameSet.get_base64_images(
                    self.args.get_base64_images))
            if self.args.update_game_details:
                self.gameSet.update_game_details(
                    self.args.update_game_details)
            if self.args.download_game:
                install_dir = self.args.install_dir or os.environ.get('INSTALL_DIR', os.path.expanduser('~/Games/itchio/'))
                self.gameSet.download_game(self.args.download_game, install_dir)
            if self.args.detect_executable:
                self.gameSet.detect_executable(self.args.detect_executable)
            if self.args.get_game_size:
                print(self.gameSet.get_game_size(
                    self.args.get_game_size[0], self.args.get_game_size[1]))
            if self.args.browse_games is not None:
                filter_text = self.args.browse_games[0] if self.args.browse_games else ''
                print(self.gameSet.browse_games(filter_text))
            if self.args.get_collections:
                print(self.gameSet.get_collections())
            if self.args.get_itch_tabs:
                print(self.gameSet.get_itch_tabs())
            if self.args.add_browse_to_library:
                print(self.gameSet.add_browse_to_library(self.args.add_browse_to_library))
            if self.args.get_browse_details:
                print(self.gameSet.get_browse_details(self.args.get_browse_details))
            if not any(vars(self.args).values()):
                self.parser.print_help()
        except itchio.CmdException as e:
            print(json.dumps(
                {'Type': 'Error', 'Content': {'Message': e.args[0]}}))


def main():
    itchioArgs = ItchioArgs("Itchio", "Proton")
    itchioArgs.parseArgs()
    itchioArgs.processArgs()


if __name__ == '__main__':
    main()
