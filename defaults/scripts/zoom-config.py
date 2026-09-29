#!/usr/bin/env python
import argparse
import json
import os
import sys

import GameSet
import zoom


class ZoomArgs(GameSet.GenericArgs):
    def __init__(self, storeName, setNameConfig):
        super().__init__()
        self.addArguments()
        self.setNameConfig = setNameConfig
        self.storeName = storeName

    def addArguments(self):
        super().addArguments()
        self.parser.add_argument(
            '--list', help='Refresh the ZOOM library', action='store_true')
        self.parser.add_argument(
            '--getloginstatus', help='Get login status', action='store_true')
        self.parser.add_argument(
            '--flush-cache', help='Flush cache', action='store_true')
        self.parser.add_argument(
            '--login', nargs=2, metavar=('EMAIL', 'PASSWORD'),
            help='Log in to ZOOM Platform')
        self.parser.add_argument(
            '--two-factor', help='Answer a two-factor challenge with a code')
        self.parser.add_argument(
            '--logout', help='Log out of ZOOM Platform', action='store_true')
        self.parser.add_argument(
            '--download-game', help='Download a game by product UUID')
        self.parser.add_argument(
            '--install-game', help='Download and install a game by product UUID')
        self.parser.add_argument(
            '--uninstall-game', help='Remove an installed game by product UUID')
        self.parser.add_argument(
            '--install-dir', help='Directory games are installed into')
        self.parser.add_argument(
            '--installer-script', help='Path to zoom-platform.sh')
        self.parser.add_argument(
            '--get-product', help='Dump one product record as JSON')
        self.parser.add_argument(
            '--check-update', help='Report whether a newer release exists')
        self.parser.add_argument(
            '--getprogress', help='Read installation progress from a log')
        self.parser.add_argument(
            '--detect-executable', help='Find and record the launcher for an installed game')
        self.parser.add_argument(
            '--get-game-dir', help='Print the install directory for a game')
        self.parser.add_argument(
            '--get-game-size', nargs=2, help='Get game size')
        self.parser.add_argument(
            '--launchoptions', nargs=3, help='Get launch options')
        self.parser.add_argument(
            '--get-base64-images', help='Get base64 images for a short name')

    def parseArgs(self):
        super().parseArgs()
        self.gameSet = zoom.Zoom(self.args.dbfile, self.storeName, self.setNameConfig)
        self.gameSet.create_tables()

    def _install_dir(self):
        return (
            self.args.install_dir
            or os.environ.get('INSTALL_DIR')
            or os.path.expanduser('~/Games/zoom/')
        )

    def _installer_script(self):
        return (
            self.args.installer_script
            or os.environ.get('ZOOM_INSTALLER')
            or os.path.expanduser('~/.local/bin/zoom-platform.sh')
        )

    def processArgs(self):
        try:
            super().processArgs()

            if self.args.login:
                print(self.gameSet.login(self.args.login[0], self.args.login[1]))
            if self.args.two_factor:
                print(self.gameSet.two_factor(self.args.two_factor))
            if self.args.logout:
                print(self.gameSet.logout())
            if self.args.getloginstatus:
                print(self.gameSet.get_login_status(self.args.flush_cache))

            if self.args.list:
                found = self.gameSet.get_list()
                print(json.dumps({
                    'Type': 'RefreshContent',
                    'Content': {'Message': f'{len(found)} game(s) in your ZOOM library'},
                }))

            if self.args.get_product:
                print(json.dumps(self.gameSet.get_product(self.args.get_product)))
            if self.args.check_update:
                print(json.dumps({
                    'Type': 'UpdateAvailable',
                    'Content': {'Available': self.gameSet.update_available(self.args.check_update)},
                }))

            if self.args.download_game:
                self.gameSet.download_game(self.args.download_game, self._install_dir())
            if self.args.install_game:
                path = self.gameSet.install_game(
                    self.args.install_game, self._install_dir(), self._installer_script())
                print(json.dumps({'Type': 'Install', 'Content': {'Path': path}}))
            if self.args.uninstall_game:
                print(self.gameSet.uninstall_game(self.args.uninstall_game))

            if self.args.detect_executable:
                print(self.gameSet.detect_executable(self.args.detect_executable))
            if self.args.getprogress:
                print(self.gameSet.get_last_progress_update(self.args.getprogress))
            if self.args.get_game_dir:
                conn = self.gameSet.get_connection()
                c = conn.cursor()
                c.execute("SELECT InstallPath FROM Game WHERE ShortName=?",
                          (self.args.get_game_dir,))
                row = c.fetchone()
                conn.close()
                print(row[0] if row and row[0] else "")
            if self.args.get_game_size:
                print(self.gameSet.get_game_size(
                    self.args.get_game_size[0], self.args.get_game_size[1]))
            if self.args.launchoptions:
                print(self.gameSet.get_lauch_options(
                    self.args.launchoptions[0], self.args.launchoptions[1],
                    self.args.launchoptions[2]))
            if self.args.get_base64_images:
                print(self.gameSet.get_base64_images(self.args.get_base64_images))

            if not any(vars(self.args).values()):
                self.parser.print_help()

        except zoom.ZoomError as e:
            print(json.dumps({'Type': 'Error', 'Content': {'Message': e.args[0]}}))
            print(f"{zoom.ERROR_MARKER} {e.args[0]}", file=sys.stderr)
        except Exception as e:
            print(json.dumps({'Type': 'Error', 'Content': {'Message': str(e)}}))
            print(f"{zoom.ERROR_MARKER} {e}", file=sys.stderr)


def main():
    args = ZoomArgs("Zoom", "Proton")
    args.parseArgs()
    args.processArgs()


if __name__ == '__main__':
    main()
