import CameraContainer from "../Camera/Container";
import PlayerCamera from "./../Camera/Camera";

import { Skull } from "./../../assets/Icons";
import { apiUrl } from "../../API";
import defaultSteamAvatar from "../../assets/images/steam_avatar_default.jpg";
import defaultCtAgent from "../../assets/images/default_CT.png";
import defaultTAgent from "../../assets/images/default_T.png";

interface IProps {
  steamid: string;
  url: string | null;
  slot?: number;
  height?: number;
  width?: number;
  showSkull?: boolean;
  showCam?: boolean;
  sidePlayer?: boolean;
  useAgent?: boolean;
  teamSide?: "CT" | "T";
  teamId?: string | null
}
const Avatar = (
  { steamid, url, height, width, showCam, showSkull, sidePlayer, useAgent, teamSide, teamId }: IProps,
) => {
  const uploadedAvatarUrl = url?.startsWith('/')
    ? `${apiUrl.replace(/\/$/, '')}${url}`
    : url;
  const profileAvatarUrl = uploadedAvatarUrl || defaultSteamAvatar;
  const avatarUrl = useAgent ? (teamSide === "CT" ? defaultCtAgent : defaultTAgent) : profileAvatarUrl;
  return (
    <div className={`avatar`}>
      {showCam
        ? (sidePlayer
          ? (
            <div className="videofeed">
              <PlayerCamera steamid={steamid} visible={true} />
            </div>
          )
          : <CameraContainer observedSteamid={steamid} />)
        : null}
      {showSkull
        ? <Skull height={height} width={width} />
        : (
          avatarUrl ? <img
            src={avatarUrl}
            height={height}
            width={width}
            alt={"Avatar"}
            onError={(event) => {
              if (event.currentTarget.src !== defaultSteamAvatar) {
                event.currentTarget.src = defaultSteamAvatar;
              }
            }}
          /> : null
        )}
    </div>
  );
};
export default Avatar;
