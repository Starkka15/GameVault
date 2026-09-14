import { useParams } from "@decky/ui";
import { FC } from "react";
import { GameDetailsItem } from "./GameDetailsItem";

interface GameDetailsPageProperties {
  
  clearActiveGame: () => void;
}

export const GameDetailsPage: FC<GameDetailsPageProperties> = ({
  clearActiveGame
}) => {

  const { initActionSet, initAction, shortname } = useParams<{
    initActionSet: string;
    initAction: string;
    shortname: string
  }>();
  return (
    <GameDetailsItem shortname={shortname} initActionSet={initActionSet} initAction={initAction} clearActiveGame={clearActiveGame} />
  )
}

