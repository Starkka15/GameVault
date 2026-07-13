#!/usr/bin/env python
import optima
import json
import argparse
import os
import sys

import GameSet


class OptimaArgs(GameSet.GenericArgs):
    def __init__(self, storeName, setNameConfig):
        super().__init__()
        self.addArguments()
        self.setNameConfig = setNameConfig
        self.storeName = storeName

    def addArguments(self):
        super().addArguments()
        self.parser.add_argument(
            '--list', help='Get list of owned Ubisoft games', action='store_true')
        self.parser.add_argument(
            '--get-game-dir', help='Get install directory for a product id')
        self.parser.add_argument(
            '--getprogress', help='Get installation progress for a product id')
        self.parser.add_argument(
            '--get-args', help='Get game arguments')
        self.parser.add_argument(
            '--launchoptions', nargs=3, help='Get launch options')
        self.parser.add_argument(
            '--getloginstatus', help='Get login status', action='store_true')
        self.parser.add_argument(
            '--get-base64-images', help='Get base64 images for a product id')
        self.parser.add_argument(
            '--offline', help='Offline mode', action='store_true')
        self.parser.add_argument(
            '--get-game-size', nargs=2, help='Get game size')
        self.parser.add_argument(
            '--flush-cache', help='Flush cache', action='store_true')
        self.parser.add_argument(
            '--download-game', help='Download a product by id')
        self.parser.add_argument(
            '--install-dir', help='Install directory for downloads')
        self.parser.add_argument(
            '--get-profile', help='Get the Ubisoft account form (IniEditor)', action='store_true')
        self.parser.add_argument(
            '--save-profile', help='Save the Ubisoft account form (reads JSON on stdin)', action='store_true')

    def parseArgs(self):
        super().parseArgs()
        self.gameSet = optima.Optima(self.args.dbfile, self.storeName, self.setNameConfig)
        self.gameSet.create_tables()

    def processArgs(self):
        try:
            super().processArgs()

            if self.args.list:
                self.gameSet.get_list(self.args.offline)
            if self.args.get_game_dir:
                self.gameSet.get_game_dir(self.args.get_game_dir)
            if self.args.getprogress:
                print(self.gameSet.get_last_progress_update(self.args.getprogress))
            if self.args.get_args:
                conn = self.gameSet.get_connection()
                c = conn.cursor()
                c.execute("SELECT Arguments FROM Game WHERE ShortName=?", (self.args.get_args,))
                result = c.fetchone()
                conn.close()
                print(result[0] if result and result[0] else "")
            if self.args.launchoptions:
                print(self.gameSet.get_lauch_options(
                    self.args.launchoptions[0], self.args.launchoptions[1],
                    self.args.launchoptions[2], self.args.offline))
            if self.args.getloginstatus:
                print(self.gameSet.get_login_status(self.args.flush_cache))
            if self.args.get_base64_images:
                print(self.gameSet.get_base64_images(self.args.get_base64_images))
            if self.args.download_game:
                install_dir = self.args.install_dir or os.environ.get(
                    'INSTALL_DIR', os.path.expanduser('~/Games/optima/'))
                self.gameSet.download_game(self.args.download_game, install_dir)
            if self.args.get_game_size:
                print(self.gameSet.get_game_size(
                    self.args.get_game_size[0], self.args.get_game_size[1]))
            if self.args.get_profile:
                print(self.gameSet.get_profile())
            if self.args.save_profile:
                raw = sys.stdin.read()
                print(self.gameSet.save_profile(raw))
            if not any(vars(self.args).values()):
                self.parser.print_help()
        except optima.CmdException as e:
            print(json.dumps({'Type': 'Error', 'Content': {'Message': e.args[0]}}))


def main():
    optimaArgs = OptimaArgs("Optima", "Proton")
    optimaArgs.parseArgs()
    optimaArgs.processArgs()


if __name__ == '__main__':
    main()
