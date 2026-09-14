import { call, toaster, ToastData } from "@decky/api";
import { showModal } from "@decky/ui";
import { ContentError, ContentResult, ContentType, ExecuteArgs, LaunchOptions, SuccessContent } from "../Types/Types";
import Logger from "./logger";
import { ErrorModal } from "../ErrorModal";
import { runApp, configureShortcut, getAppDetails, gameIDFromAppID } from './utils';

//* this is where you will be assuming the type of content and if the case is amibigous you can use type unions and deal with each possiblitiy outside the function
export async function executeAction<Arguments extends ExecuteArgs, Content extends ContentType>(actionSet: string, actionName: string, args: Arguments, onExeExit?: () => void): Promise<ContentResult<Content> | null> {

    const logger = new Logger("executeAction");
    // logger.log(`actionSet: ${actionSet}, actionName: ${actionName}`);
    // logger.debug("Args: ", args);

    // Decky's new API (`call`) passes a single payload object and throws on a
    // backend exception, instead of the old `{ success, result }` envelope. The
    // Python side unpacks this object explicitly (see main.py execute_action),
    // preserving the previous kwargs-spreading behaviour.
    let result: ContentResult<Content | LaunchOptions | ContentError> | null;
    try {
        result = await call<[payload: object], ContentResult<Content | LaunchOptions | ContentError> | null>("execute_action", {
            actionSet: actionSet,
            actionName: actionName,
            ...args
        });
    } catch (e) {
        logger.error("Server error:", e);
        toaster.toast({
            title: "GameVault",
            body: `Action failed: ${actionName}`,
        });
        return null;
    }

    if (!result) {
        logger.error("Server returned no result for:", actionName);
        toaster.toast({
            title: "GameVault",
            body: `Action failed: ${actionName}`,
        });
        return null;
    }

    if (result.Type === 'RunExe') {
        const newLaunchOptions = result.Content as LaunchOptions;
        if (args.appId) {
            const id = parseInt(args.appId, 10);
            if (Number.isNaN(id)) {
                logger.error("Invalid appId:", args.appId);
                return null;
            }
            const details = await getAppDetails(id);
            logger.log("details: ", details);
            const oldLaunchOptions: LaunchOptions = {
                Name: details?.strDisplayName || "",
                Exe: details?.strShortcutExe || "",
                WorkingDir: details?.strShortcutStartDir || "",
                Options: details?.strShortcutLaunchOptions || "",
                CompatToolName: details?.strCompatToolName,
                Compatibility: !!details?.strCompatToolName
            };
            configureShortcut(id, newLaunchOptions);
            const gid = gameIDFromAppID(id);
            if (!gid || gid === -1) {
                logger.error("Failed to get gameID for appId, restoring shortcut:", id);
                configureShortcut(id, oldLaunchOptions);
            } else {
                // Fallback: restore shortcut if app never starts within 30s
                const restoreTimeout = setTimeout(() => {
                    logger.error("App never started within 30s, restoring shortcut:", id);
                    configureShortcut(id, oldLaunchOptions);
                }, 30000);
                runApp(id, onExeExit, () => {
                    clearTimeout(restoreTimeout);
                    configureShortcut(id, oldLaunchOptions);
                });
            }
        }

        return null;
    }

    if (result.Type === 'Success') {
        const success = result.Content as SuccessContent;
        logger.debug("result: ", result);
        const data: ToastData = {
            title: "GameVault",
            body: success.Message,
        };
        if (success.Title) {
            data.title = success.Title;
        }

        if (success.Toast !== false) {
            logger.debug("toasting: ", data);
            toaster.toast(data);
        }
    }

    if (result.Type === 'Error') {
        const error = result.Content as ContentError; //only acceptable if this is gauranteed that in this case (result.Type === 'Error') Content is indeed ContentError
        showModal(<ErrorModal Error={error} />);
        logger.error("result: ", result);
        return null;
    }

    return result as ContentResult<Content>; //only acceptable because we've handle the other possibilities explicitly
}
