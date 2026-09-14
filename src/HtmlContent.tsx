import { DialogBody, DialogControlsSection } from "@decky/ui";
import { FC } from "react";


export const HtmlContent: FC<{ content: string; }> = ({ content }) => {

    return (
        <DialogBody>
            <DialogControlsSection style={{ height: "calc(100%)" }}>
                <div dangerouslySetInnerHTML={{ __html: content }} />
            </DialogControlsSection>
        </DialogBody>
    );
};
