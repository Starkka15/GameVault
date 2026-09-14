import { ModalRoot, ModalRootProps } from "@decky/ui";
import { FC } from "react";
import { Content } from "./ContentTabs";

export interface MainMenuModalProps extends ModalRootProps {
}
export const MainMenuModal: FC<MainMenuModalProps> = ({ onCancel, onOK, onEscKeypress, bAllowFullSize, bCancelDisabled, bOKDisabled, closeModal }) => {
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
            <Content initActionSet="init" initAction="InitActions" closeModal={closeModal} />
        </ModalRoot>
    );
};
