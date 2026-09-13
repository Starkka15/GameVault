import { definePlugin, routerHook, toaster } from "@decky/api";
import { Navigation, showModal, staticClasses, useParams } from "@decky/ui";
import { FaBoxOpen } from "react-icons/fa";

import { Content } from "./ContentTabs";
import { About } from "./About";
import { addAchievement, toastFactory } from "./Utils/achievements";
import { MainMenuModal } from "./MainMenuModal";
import { DownloadsPage } from "./Components/DownloadsPage";
import { installQueue } from "./Utils/installQueue";




export default definePlugin(() => {


  toastFactory(toaster);
  let l3Pressed = false;
  let r3Pressed = false;
  let modalDebounce = false;
  const doubleStickEnabled = localStorage.getItem('gv_doubleStick') === 'true';

  const unregister = SteamClient.Input.RegisterForControllerInputMessages(
    (e) => {
      if (Array.isArray(e)) {
        if (e[0]) {
          if (e[0].nA == 25) {
            l3Pressed = e[0].bS;
          }
          if (e[0].nA == 41) {
            r3Pressed = e[0].bS;
          }
        }
      }

      if (l3Pressed && r3Pressed && doubleStickEnabled && !modalDebounce) {
        modalDebounce = true;
        Navigation.CloseSideMenus();
        showModal(<MainMenuModal />);
        setTimeout(() => { modalDebounce = false; }, 1000);
      }
    })



  const currentTime = new Date();
  const currentHour = currentTime.getHours();
  const currentMinute = currentTime.getMinutes();

  if (currentHour === 0 && currentMinute >= 0 && currentMinute <= 15) {
    addAchievement("MTAx")
  }
  const currentDate = new Date();
  if (currentDate.getDay() === 5 && currentDate.getDate() === 13) {
    addAchievement("MTEw")
  }

  routerHook.addRoute(
    "/gamevault-content/:initActionSet/:initAction",
    () => {
      const { initActionSet, initAction } = useParams<{ initActionSet: string; initAction: string }>();
      return <Content key={initActionSet + "_" + initAction} initActionSet={initActionSet} initAction={initAction} />;
    },
    {
      exact: true,
    }
  );
  routerHook.addRoute(
    "/about-gamevault",
    () => {
      return <About />
    },
    {
      exact: true,
    }
  );
  routerHook.addRoute(
    "/gamevault-downloads",
    () => {
      return <DownloadsPage />
    },
    {
      exact: true,
    }
  );
  // Reconnect to any in-progress downloads that survived a close/reopen
  installQueue.reconnect();




  return {
    name: "GameVault",
    titleView: <div className={staticClasses.Title}>GameVault</div>,
    content: <Content initActionSet="init" initAction="InitActions" />,
    icon: <FaBoxOpen />,
    onDismount() {
      routerHook.removeRoute("/gamevault-content/:initActionSet/:initAction");
      routerHook.removeRoute("/about-gamevault");
      routerHook.removeRoute("/gamevault-downloads");
      unregister.unregister();
      installQueue.clear();
    },
  };
});
