import { DialogBody, DialogControlsSection } from "@decky/ui";
import { FC } from "react";


export const TextContent: FC<{ content: string; }> = ({ content }) => {
    return (
        <DialogBody>
            <DialogControlsSection style={{ height: "calc(100%)" }}>
                {content}
            </DialogControlsSection>
        </DialogBody>
    );
};
