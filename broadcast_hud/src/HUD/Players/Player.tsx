import * as I from "csgogsi";
import Weapon from "./../Weapon/Weapon";
import Avatar from "./Avatar";
import React, { CSSProperties, useEffect, useRef, useState } from "react";
import { ArmorFull, ArmorHelmet, C4, Defuse, Skull } from "../../assets/Icons";

interface IProps {
  player: I.Player,
  isObserved: boolean,
}

const compareWeapon = (weaponOne: I.WeaponRaw, weaponTwo: I.WeaponRaw) => {
  if (weaponOne.name === weaponTwo.name &&
    weaponOne.paintkit === weaponTwo.paintkit &&
    weaponOne.type === weaponTwo.type &&
    weaponOne.ammo_clip === weaponTwo.ammo_clip &&
    weaponOne.ammo_clip_max === weaponTwo.ammo_clip_max &&
    weaponOne.ammo_reserve === weaponTwo.ammo_reserve &&
    weaponOne.state === weaponTwo.state
  ) return true;

  return false;
}

const compareWeapons = (weaponsObjectOne: I.Weapon[], weaponsObjectTwo: I.Weapon[]) => {
  const weaponsOne = [...weaponsObjectOne].sort((a, b) => a.name.localeCompare(b.name))
  const weaponsTwo = [...weaponsObjectTwo].sort((a, b) => a.name.localeCompare(b.name))

  if (weaponsOne.length !== weaponsTwo.length) return false;

  return weaponsOne.every((weapon, i) => compareWeapon(weapon, weaponsTwo[i]));
}

const arePlayersEqual = (playerOne: I.Player, playerTwo: I.Player) => {
  if (playerOne.name === playerTwo.name &&
    playerOne.steamid === playerTwo.steamid &&
    playerOne.observer_slot === playerTwo.observer_slot &&
    playerOne.defaultName === playerTwo.defaultName &&
    playerOne.clan === playerTwo.clan &&
    playerOne.stats.kills === playerTwo.stats.kills &&
    playerOne.stats.assists === playerTwo.stats.assists &&
    playerOne.stats.deaths === playerTwo.stats.deaths &&
    playerOne.stats.mvps === playerTwo.stats.mvps &&
    playerOne.stats.score === playerTwo.stats.score &&
    playerOne.state.health === playerTwo.state.health &&
    playerOne.state.armor === playerTwo.state.armor &&
    playerOne.state.helmet === playerTwo.state.helmet &&
    playerOne.state.defusekit === playerTwo.state.defusekit &&
    playerOne.state.flashed === playerTwo.state.flashed &&
    playerOne.state.smoked === playerTwo.state.smoked &&
    playerOne.state.burning === playerTwo.state.burning &&
    playerOne.state.money === playerTwo.state.money &&
    playerOne.state.round_killhs === playerTwo.state.round_killhs &&
    playerOne.state.round_kills === playerTwo.state.round_kills &&
    playerOne.state.round_totaldmg === playerTwo.state.round_totaldmg &&
    playerOne.state.equip_value === playerTwo.state.equip_value &&
    playerOne.state.adr === playerTwo.state.adr &&
    playerOne.avatar === playerTwo.avatar &&
    !!playerOne.team.id === !!playerTwo.team.id &&
    playerOne.team.side === playerTwo.team.side &&
    playerOne.country === playerTwo.country &&
    playerOne.realName === playerTwo.realName &&
    compareWeapons(playerOne.weapons, playerTwo.weapons)
  ) return true;

  return false;
}
const Player = ({ player, isObserved }: IProps) => {

  const previousHealth = useRef(player.state.health);
  const [recentDamage, setRecentDamage] = useState(Number(player.extra?.recentDamage) || 0);

  useEffect(() => {
    const healthLost = previousHealth.current - player.state.health;
    previousHealth.current = player.state.health;
    if (healthLost <= 0) return;
    setRecentDamage(healthLost);
    const timeout = window.setTimeout(() => setRecentDamage(0), 1400);
    return () => window.clearTimeout(timeout);
  }, [player.state.health]);

  const weapons = player.weapons.map(weapon => ({ ...weapon, name: weapon.name.replace("weapon_", "") }));
  const primary = weapons.filter(weapon => !['C4', 'Pistol', 'Knife', 'Grenade', undefined].includes(weapon.type))[0] || null;
  const secondary = weapons.filter(weapon => weapon.type === "Pistol")[0] || null;
  const displayedWeapon = primary || secondary;
  const grenades = weapons.filter(weapon => weapon.type === "Grenade");
  const hasC4 = weapons.some(weapon => weapon.type === "C4");
  const money = Math.max(0, Math.trunc(Number(player.state.money) || 0));
  const moneyClass = String(money).length >= 7 ? "money-tight" : String(money).length >= 6 ? "money-compact" : "";
  const isDead = player.state.health === 0;
  const damageEnd = isDead ? 0 : Math.min(100, player.state.health + recentDamage);
  const healthStyle = {
    "--health-pct": `${player.state.health}%`,
    "--damage-end": `${damageEnd}%`,
  } as CSSProperties;

  return (
    <div className={`player ${player.state.health === 0 ? "dead" : ""} ${isObserved ? 'active' : ''}`}>
      <div className="player_data">
        {recentDamage > 0 && !isDead ? <div key={`${player.steamid}-${player.state.health}`} className="live-player-damage">-{recentDamage}</div> : null}
        {hasC4 ? <span className="live-player-c4"><C4 /></span> : null}
        {player.state.round_kills > 0 ? <span className="live-player-round-kills"><Skull />{player.state.round_kills}</span> : null}
        <Avatar teamId={player.team.id} teamSide={player.team.side} steamid={player.steamid} url={player.avatar} height={72} width={72} showSkull={isDead} showCam={false} sidePlayer={true} />
        <div className="live-player-heading">
          <span className="live-player-slot">{player.observer_slot}</span>
          <strong
            className={player.name.length > 15 ? "name-very-long" : player.name.length > 11 ? "name-long" : ""}
            title={player.name}
          >{player.name}</strong>
          <span className="live-player-health">
            {player.state.helmet ? <ArmorHelmet /> : <ArmorFull />}
            {player.state.health}
          </span>
        </div>
        <div className="live-player-stats">
          <span className="live-player-stat"><i className="live-player-crosshair" />{player.stats.kills}</span>
          <span className="live-player-stat"><Skull />{player.stats.deaths}</span>
          <span className={`live-player-money ${moneyClass}`.trim()}>${money}</span>
        </div>
        <div className="live-player-weapon" style={healthStyle}>
          <span className="live-player-primary">{displayedWeapon ? <Weapon weapon={displayedWeapon.name} active={displayedWeapon.state === "active"} /> : null}</span>
          <span className="live-player-equipment">
            {grenades.map(grenade => <React.Fragment key={grenade.id}>
              <Weapon weapon={grenade.name} active={grenade.state === "active"} isGrenade />
              {grenade.ammo_reserve === 2 ? <Weapon weapon={grenade.name} active={grenade.state === "active"} isGrenade /> : null}
            </React.Fragment>)}
            {player.state.defusekit ? <Defuse /> : null}
          </span>
        </div>
        <div className={`hp_bar ${player.state.health <= 20 ? 'low' : ''}`} style={{ width: `${player.state.health}%` }} />
      </div>
    </div>
  );
}

const arePropsEqual = (prevProps: Readonly<IProps>, nextProps: Readonly<IProps>) => {
  if (prevProps.isObserved !== nextProps.isObserved) return false;

  return arePlayersEqual(prevProps.player, nextProps.player);
}

export default React.memo(Player, arePropsEqual);
//export default Player;
