export const ICON_BASE = '/resources/icons/match/';
export const SUPPORTED_MAPS = new Set(['dust2','mirage','inferno','nuke','overpass','ancient','anubis','vertigo','train','cache']);
export const MAP_METADATA = {
  ancient:{resolution:4.26,x:2590,y:2520},anubis:{resolution:5.25,x:2830,y:2030},
  cache:{resolution:5.54,x:2020,y:2390},dust2:{resolution:4.4,x:2470,y:1255},
  inferno:{resolution:4.91,x:2090,y:1150},mirage:{resolution:5.02,x:3240,y:3410},
  nuke:{resolution:6.98,x:3290,y:5990,floors:[['upper',-480,5000],['lower',-2500,-481]]},
  overpass:{resolution:5.18,x:4830,y:3540},train:{resolution:4.74,x:2730,y:2360},
  vertigo:{resolution:4.96,x:3890,y:3800,floors:[['upper',11680,14000],['lower',0,11679]]}
};
// 武器图标：游戏里的武器名 → 图标文件（白色图标，浅色主题下由样式变深）
export const WEAPON_ICON_FILES = {
  ak47:'ak47.webp', aug:'aug.svg', awp:'awp.webp', bizon:'bizon.svg', cz75a:'cz75a.svg',
  deagle:'deagle.webp', elite:'elite.webp', famas:'famas.webp', fiveseven:'fiveseven.webp',
  g3sg1:'g3sg1.svg', galilar:'galilar.webp', glock:'glock.webp', hkp2000:'hkp2000.png',
  m249:'m249.svg', m4a1:'m4a1.webp', m4a1_silencer:'m4a1_silencer.webp', mag7:'mag7.svg',
  mac10:'mac10.webp', mp5sd:'mp5sd.svg', mp7:'mp7.webp', mp9:'mp9.webp', negev:'negev.svg',
  nova:'nova.svg', p90:'p90.svg', p250:'p250.webp', revolver:'revolver.svg', sawedoff:'sawedoff.svg',
  scar20:'scar20.svg', sg556:'sg556.svg', ssg08:'ssg08.svg', tec9:'tec9.webp', ump45:'ump45.svg',
  usp_silencer:'usp_silencer.webp', xm1014:'xm1014.svg', knife:'knife.webp', taser:'taser.svg',
  flashbang:'flashbang.webp', hegrenade:'hegrenade.webp', smokegrenade:'smokegrenade.svg',
  molotov:'molotov.svg', incgrenade:'incgrenade.svg', decoy:'decoy.svg'
};
const WEAPON_ALIASES = {
  ak_47:'ak47', desert_eagle:'deagle', dual_berettas:'elite', five_seven:'fiveseven',
  galil_ar:'galilar', glock_18:'glock', m4a4:'m4a1', m4a1_s:'m4a1_silencer', m4a1silencer:'m4a1_silencer',
  m4a1_silencer_off:'m4a1_silencer', usp_s:'usp_silencer', uspsilencer:'usp_silencer', usp_silencer_off:'usp_silencer',
  cz75_auto:'cz75a', pp_bizon:'bizon', r8_revolver:'revolver',
  high_explosive_grenade:'hegrenade', he_grenade:'hegrenade',
  smoke_grenade:'smokegrenade', incendiary_grenade:'incgrenade', incendiary:'incgrenade'
};

export function mapKey(name){return String(name||'').toLowerCase().replace('de_','').replace(/[^a-z0-9]/g,'')}
export function mapDisplay(name){return String(name||'').replace(/^(de_|cs_)/i,'').replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase()})}
function weaponKey(name){
  let key=String(name||'').trim().toLowerCase().replace(/^weapon_/,'').replace(/[\s-]+/g,'_').replace(/[^a-z0-9_]/g,'');
  if(key.startsWith('knife'))return 'knife';
  return WEAPON_ALIASES[key]||key;
}
export function weaponAsset(name){
  if(!name||name==='-')return '';
  const file=WEAPON_ICON_FILES[weaponKey(name)];
  return file?ICON_BASE+file:'';
}
