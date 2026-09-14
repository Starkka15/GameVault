import { ConfirmModal, DialogButton, ToggleField, showModal } from "@decky/ui";
import { FC, useState } from "react";
import { resetAchievements } from "./Utils/achievements";


export const Developer: FC = () => {

    const [logging] = useState(localStorage.getItem('enableLogger') === 'true');
    const [firstLaunch] = useState(localStorage.getItem('js_firstlaunch') === 'true');
    const [doubleStick] = useState(localStorage.getItem('js_doubleStick') === 'true');
    const toggleFirstLaunch = async (value: string) => {
        localStorage.setItem('js_firstlaunch', value);
    }
    const toggleLogging = async (value: string) => {
        localStorage.setItem('enableLogger', value);
    }
    const toggleDoubleStick = async (value: string) => {
        localStorage.setItem('js_doubleStick', value);
    }
    return (
        <div>
            <ToggleField
                label="Enable UI Logging"
                checked={logging}
                onChange={(newValue) => toggleLogging(newValue.toString())}


            />
            <ToggleField
                label="Set first Launch"
                checked={firstLaunch}
                onChange={(newValue) => toggleFirstLaunch(newValue.toString())}
            />
            <ToggleField
                label="Enable double stick quick access"
                checked={doubleStick}
                onChange={(newValue) => toggleDoubleStick(newValue.toString())}
            />
            <DialogButton

                onClick={async () => {
                    showModal(<ConfirmModal strTitle="Confirm" strDescription={"Reset all achievements?"} onOK={() => { resetAchievements(); }} />)
                }}
            >
                Reset Achievements
            </DialogButton>
        </div>
    );
};
