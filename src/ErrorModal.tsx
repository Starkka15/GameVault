import { PanelSection, ModalRoot, Focusable } from "@decky/ui";
import { FC } from "react";
import { ErrorModalProps } from "./ConfEditor";
import { ErrorDisplay } from "./Components/ErrorDisplay";
import { addAchievement } from "./Utils/achievements";


export const ErrorModal: FC<ErrorModalProps> = ({ Error, onCancel, onOK, onEscKeypress, bAllowFullSize, bCancelDisabled, bOKDisabled, closeModal }) => {
    addAchievement("MQ==")
    return (
        <ModalRoot
            onCancel={onCancel}
            onOK={onOK}
            onEscKeypress={onEscKeypress}
            bAllowFullSize={bAllowFullSize}
            bCancelDisabled={bCancelDisabled}
            bOKDisabled={bOKDisabled}
            closeModal={closeModal}
        >
            <Focusable noFocusRing={false}>
                <PanelSection title="GameVault Error">
                    <ErrorDisplay error={Error} />

                </PanelSection>
            </Focusable>
        </ModalRoot>
    );
};
