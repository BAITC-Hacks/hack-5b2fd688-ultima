(function () {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const WIDTH = 1000;
  const HEIGHT = 660;
  const CITY_VIEW = `0 0 ${WIDTH} ${HEIGHT}`;
  const RIVER_PATH = 'M-20 333C111 234 186 309 282 331S419 287 485 308 592 382 679 348C706 335 716 351 734 384S770 452 807 464 937 459 1020 499';
  let mapSequence = 0;

  // Deliberately schematic geometry: neither administrative borders nor approved routes.
  // Five independent object slots per district keep labels and landmarks unobstructed.
  const GEOMETRY = {
    saryarka: {
      path: 'M66 65 386 52 413 264 363 297 231 286 160 273 60 292Z',
      label: [100, 82], center: [235, 175], zoom: 2.05,
      slots: [[127, 151], [235, 151], [337, 151], [175, 234], [294, 238]],
      route: 'M85 117Q190 105 325 115Q376 118 378 167L379 228Q378 263 341 271L213 267 113 255Q82 252 82 216Z',
    },
    baikonur: {
      path: 'M399 52 673 59 732 142 695 271 618 317 519 298 426 285Z',
      label: [439, 86], center: [568, 183], zoom: 2.1,
      slots: [[472, 166], [568, 166], [664, 173], [482, 249], [587, 262]],
      route: 'M431 127Q541 109 637 133Q695 144 700 186L681 248Q669 278 612 295L468 275Q432 266 433 231Z',
    },
    almaty: {
      path: 'M747 133 922 156 953 337 932 465 792 446 730 354 708 277Z',
      label: [774, 181], center: [827, 305], zoom: 1.85,
      slots: [[783, 256], [886, 256], [787, 334], [891, 337], [853, 418]],
      route: 'M752 219Q839 202 916 226L928 321Q932 397 910 439L807 429Q772 393 757 355L741 279Q731 241 752 219Z',
    },
    nura: {
      path: 'M57 322 147 300 244 337 352 362 423 342 445 544 333 581 111 557 49 460Z',
      label: [101, 356], center: [243, 455], zoom: 2,
      slots: [[125, 429], [232, 429], [338, 429], [158, 509], [280, 511]],
      route: 'M82 403Q150 391 217 387L367 381Q403 382 410 418L420 515Q405 548 376 556L145 548Q92 535 84 476Z',
    },
    esil: {
      path: 'M464 347 529 345 619 393 713 363 772 459 923 481 885 580 661 608 469 596Z',
      label: [502, 404], center: [692, 487], zoom: 1.85,
      slots: [[525, 477], [628, 477], [732, 478], [548, 555], [674, 558]],
      route: 'M489 439Q562 426 647 427L728 404Q754 432 766 462L889 503Q912 534 867 568L684 598 512 592Q482 577 485 523Z',
    },
  };

  const SHORT_NAMES = {
    M1: 'Автобусы', M2: 'Светофоры', M3: 'ЛРТ', M4: 'Парк', M5: 'Чистое тепло',
    M6: 'Зелёный пояс', M7: 'Школа и сад', M8: 'Поликлиника', M9: 'Спорт-хаб',
    M10: 'Свет и камеры', M11: 'Переходы', M12: 'Обращения', M13: 'Сети ЖКХ', M14: 'Аварийная служба',
  };

  function element(tag, attributes = {}, text) {
    const node = document.createElementNS(NS, tag);
    Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, String(value)));
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function tree(x, y, size = 1, delay = 0) {
    return `<g transform="translate(${x} ${y}) scale(${size})"><g class="am-tree" style="--am-delay:${delay}ms"><path d="M0 0V-16" class="am-tree-trunk"/><path d="M-12-16C-16-29-7-38 0-37 10-39 17-26 11-17 8-9-8-9-12-16Z" class="am-tree-crown"/><path d="M0-29V-12M0-21 6-26" class="am-tree-vein"/></g></g>`;
  }

  function vehicle(kind) {
    if (kind === 'train') return `<g class="am-train" transform="translate(50 34)"><rect x="-25" y="-8" width="50" height="16" rx="7" fill="#fff" stroke="#4265b6" stroke-width="1.5"/><path d="M-20 4H20" stroke="#497af5" stroke-width="3"/><path d="M-6-7V7M9-7V7" stroke="#a9bddc"/><path d="M-19-3H-12M-1-3H5M14-3H19" stroke="#80b9dc" stroke-width="4" stroke-linecap="round"/></g>`;
    return `<g class="am-bus" transform="translate(50 35)"><rect x="-16" y="-10" width="32" height="19" rx="5" fill="#4876e5" stroke="#2f529a" stroke-width="1.5"/><path d="M-10-4H-5M0-4H5M10-4H11" stroke="#dcefff" stroke-width="5"/><path d="M-12 3H12" stroke="#b5d3fa" stroke-width="2"/><circle cx="-9" cy="10" r="3" fill="#33496f"/><circle cx="10" cy="10" r="3" fill="#33496f"/></g>`;
  }

  // Artwork is constant SVG; API-provided names are always inserted as text, never markup.
  function artwork(id) {
    switch (id) {
      case 'M1': return `<path d="M3 40H97" stroke="#d7e5fb" stroke-width="25" stroke-linecap="round"/><path d="M5 50H95" stroke="#6b91d2" stroke-width="2" stroke-dasharray="6 5"/><path d="M7 27H93" stroke="#fff" stroke-width="3"/>${vehicle('bus')}<path d="M83 10V24M78 10H88" stroke="#547ac5" stroke-width="2"/><rect x="77" y="4" width="12" height="10" rx="3" fill="#e9f2ff" stroke="#547ac5"/>`;
      case 'M2': return `<path d="M6 44H94M50 4V58" stroke="#dce5ec" stroke-width="17"/><path d="M6 44H94M50 4V58" stroke="#fff" stroke-width="2" stroke-dasharray="5 5"/><path d="M29 26V54M74 23V51" stroke="#647997" stroke-width="3"/><rect x="22" y="2" width="14" height="29" rx="5" fill="#385170"/><circle cx="29" cy="9" r="3" fill="#e5a59b"/><circle cx="29" cy="17" r="3" fill="#e9c888"/><circle class="am-signal" cx="29" cy="25" r="3" fill="#75d7a9"/><rect x="67" y="0" width="14" height="28" rx="5" fill="#385170"/><circle class="am-signal am-delay" cx="74" cy="7" r="3" fill="#f2a297"/><circle cx="74" cy="15" r="3" fill="#e9c888"/><circle cx="74" cy="23" r="3" fill="#a5cab6"/><path d="M40 5Q50-5 60 5M44 10Q50 4 56 10" class="am-wireless"/>`;
      case 'M3': return `<path d="M8 53H92" stroke="#dbe4ed" stroke-width="10" stroke-linecap="round"/><path d="M16 46V56M40 46V56M64 46V56M86 46V56" stroke="#a8bad0" stroke-width="4"/><path d="M5 43H95M5 47H95" stroke="#697d9e" stroke-width="1.5"/><path d="M8 45H92" stroke="#b3c2d7" stroke-width="3" stroke-dasharray="2 5"/><path d="M12 22V40M88 22V40" stroke="#758baa" stroke-width="2"/><path d="M5 22H21M80 22H96" stroke="#4f7bcf" stroke-width="5" stroke-linecap="round"/><circle cx="12" cy="45" r="3.5" fill="#fff" stroke="#4772c9"/><circle cx="88" cy="45" r="3.5" fill="#fff" stroke="#4772c9"/>${vehicle('train')}`;
      case 'M4': return `<ellipse cx="50" cy="41" rx="45" ry="18" fill="#dcefdc"/><path d="M12 48Q40 27 88 44" fill="none" stroke="#fff9dc" stroke-width="7"/>${tree(23, 43, .8, 0)}${tree(48, 35, 1, 160)}${tree(77, 45, .86, 300)}<path d="M43 49H59M45 46H57M46 49V54M56 49V54" stroke="#a58b61" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="51" r="2" fill="#edc376"/><circle cx="85" cy="52" r="2" fill="#d8b0cc"/>`;
      case 'M5': return `<ellipse cx="48" cy="50" rx="44" ry="9" fill="#e4f0e4"/><path d="M12 27H43V50H12Z" fill="#fff" stroke="#8aac9f" stroke-width="1.5"/><path d="M8 27 28 11 48 27Z" fill="#6eaa83"/><path d="M35 16V9H40V20" fill="#9abdaf"/><path d="M49 30H83V51H49Z" fill="#f5fbf7" stroke="#8aac9f" stroke-width="1.5"/><path d="M45 30 66 13 87 30Z" fill="#90bf9c"/><path d="M18 33H26V41H18ZM57 35H64V43H57Z" fill="#a5d9e7"/><path d="M32 50V36H39V50M71 51V36H78V51" fill="#b2c7b8"/><g class="am-clean-air"><path d="M43 6Q53-1 64 4M66 9Q78 0 91 5" fill="none" stroke="#a0cbb5" stroke-width="2" stroke-linecap="round"/><path d="M86 25Q80 9 96 10 99 22 86 25Z" fill="#5ca27c"/><path d="M85 29 93 15" stroke="#d1ebd4" stroke-width="1.5"/></g>`;
      case 'M6': return `<path d="M4 49Q45 28 96 48" fill="none" stroke="#d9eadb" stroke-width="15" stroke-linecap="round"/>${tree(13, 47, .62)}${tree(32, 39, .82, 110)}${tree(53, 39, 1, 220)}${tree(74, 43, .82, 330)}${tree(92, 50, .62, 440)}<path d="M7 12Q19 7 28 9M68 2Q82-1 92 3" fill="none" stroke="#a9cbb8" stroke-width="2" stroke-linecap="round"/>`;
      case 'M7': return `<path d="M8 52H93" stroke="#dcdbe8" stroke-width="5" stroke-linecap="round"/><path d="M12 24H88V50H12Z" fill="#fff8ed" stroke="#ac95bd" stroke-width="1.5"/><path d="M7 24 50 7 93 24Z" fill="#ab8ab9"/><path d="M42 50V34H57V50" fill="#ae95bb"/><path d="M21 32H28V39H21ZM33 32H39V39H33ZM64 32H71V39H64ZM77 32H83V39H77Z" fill="#adc9e4"/><circle cx="50" cy="23" r="6" fill="#fff"/><path d="M50 19V23L53 25" fill="none" stroke="#8d77a4" stroke-width="1.5"/><path d="M50 9V-2" stroke="#7d789a" stroke-width="1.5"/><path d="M51-2H65L61 3H51Z" fill="#6f9fea"/><path d="M10 47H19M80 47H90" stroke="#91b998" stroke-width="4" stroke-linecap="round"/>`;
      case 'M8': return `<path d="M9 53H93" stroke="#dfdfe9" stroke-width="5" stroke-linecap="round"/><rect x="15" y="20" width="70" height="30" rx="2" fill="#fff" stroke="#b596b3" stroke-width="1.5"/><rect x="33" y="5" width="34" height="45" rx="3" fill="#f9edf3" stroke="#b596b3" stroke-width="1.5"/><path d="M46 10H54V17H61V25H54V32H46V25H39V17H46Z" fill="#c986a2"/><path d="M44 50V37H56V50" fill="#b0c6de"/><path d="M20 28H27V34H20ZM73 28H80V34H73ZM20 39H27V45H20ZM73 39H80V45H73Z" fill="#b4d2df"/><path class="am-heartbeat" d="M30 57H41L45 53 49 60 54 53 58 57H72" fill="none" stroke="#bf7fa0" stroke-width="1.5"/>`;
      case 'M9': return `<rect x="5" y="9" width="90" height="48" rx="8" fill="#dcebdc" stroke="#93b696" stroke-width="1.5"/><rect x="12" y="16" width="76" height="34" rx="3" fill="#7db299" stroke="#f5fff6" stroke-width="1.5"/><path d="M50 16V50M12 23H22V43H12M88 23H78V43H88" fill="none" stroke="#edfaee" stroke-width="1.2"/><circle cx="50" cy="33" r="9" fill="none" stroke="#edfaee" stroke-width="1.2"/><path d="M8 32V15H20M92 32V15H80" fill="none" stroke="#7187a0" stroke-width="2"/><path d="M15 12V19M85 12V19" stroke="#fff" stroke-width="5"/><circle class="am-ball" cx="62" cy="40" r="4" fill="#e7b170" stroke="#bc8746" stroke-width="1"/>`;
      case 'M10': return `<path d="M10 53H91" stroke="#e8e6d8" stroke-width="5" stroke-linecap="round"/><path class="am-light-cone" d="M25 15 7 52H53L37 15Z" fill="#f8e9a8" opacity=".6"/><path d="M34 52V9Q34 3 27 3H17" fill="none" stroke="#7e8da5" stroke-width="3" stroke-linecap="round"/><path d="M17 3H28V10H17Z" fill="#f0cc75" stroke="#b49b65"/><path d="M69 53V23L81 16" fill="none" stroke="#7e8da5" stroke-width="3"/><path d="M59 14 78 18 76 27 57 23Z" fill="#fff" stroke="#879db8" stroke-width="1.5"/><circle class="am-camera-eye" cx="60" cy="20" r="2" fill="#598cbc"/><path d="M54 13 46 9M52 20H42M53 27 46 32" stroke="#d4b575" stroke-width="1.5" stroke-linecap="round"/>`;
      case 'M11': return `<path d="M4 36H96" stroke="#c2cedc" stroke-width="29" stroke-linecap="round"/><path d="M30 24V48M40 24V48M50 24V48M60 24V48M70 24V48" stroke="#fff" stroke-width="5"/><path d="M15 24V6M84 26V8" stroke="#7185a3" stroke-width="2"/><rect x="9" y="0" width="13" height="13" rx="2" fill="#5e8fca"/><path d="M12 10 15.5 3 19 10Z" fill="#fff"/><path d="M76 14 84-1 92 14Z" fill="#fffbeb" stroke="#d0aa60" stroke-width="2"/><path d="M84 4V8M84 10V11" stroke="#9b7945" stroke-width="1.5"/><g class="am-walker"><circle cx="52" cy="15" r="3" fill="#ddaf86"/><path d="M50 22 54 23M52 20V29M52 27 47 33M52 27 57 32" fill="none" stroke="#7182bb" stroke-width="3" stroke-linecap="round"/></g>`;
      case 'M12': return `<ellipse cx="50" cy="53" rx="35" ry="6" fill="#e4edf1"/><rect x="30" y="4" width="30" height="48" rx="6" fill="#fff" stroke="#779cae" stroke-width="2"/><path d="M39 9H50M41 47H49" stroke="#a8c4d1" stroke-width="2" stroke-linecap="round"/><g class="am-dialog"><path d="M9 13H39Q44 13 44 18V30Q44 35 39 35H23L15 41V35H9Q4 35 4 30V18Q4 13 9 13Z" fill="#67a6b8"/><path d="M14 24H34" stroke="#fff" stroke-width="3" stroke-dasharray="1 6" stroke-linecap="round"/><path d="M60 23H86Q92 23 92 29V39Q92 44 86 44H80V50L72 44H60Q55 44 55 39V29Q55 23 60 23Z" fill="#d9ede6" stroke="#8eb9a6" stroke-width="1.2"/><path d="M65 33 71 38 81 29" fill="none" stroke="#649e81" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></g>`;
      case 'M13': return `<path d="M5 52H95" stroke="#e6ecef" stroke-width="10" stroke-linecap="round"/><path d="M8 38H35V19H69V44H94" fill="none" stroke="#8eafb9" stroke-width="11" stroke-linejoin="round"/><path d="M8 38H35V19H69V44H94" fill="none" stroke="#c4e1e6" stroke-width="6" stroke-linejoin="round"/><path class="am-water-flow" d="M8 38H35V19H69V44H94" fill="none" stroke="#65a8bc" stroke-width="2" stroke-dasharray="4 9"/><path d="M24 32V44M63 30H75M78 38V50" stroke="#7297a5" stroke-width="3"/><path d="M50 19V8" stroke="#7597a6" stroke-width="3"/><g class="am-valve"><ellipse cx="50" cy="7" rx="9" ry="4" fill="#fff" stroke="#b99469" stroke-width="2"/><path d="M41 7H59M50 3V11" stroke="#b99469" stroke-width="1.5"/></g><path d="M8 22 15 8 22 22Z" fill="#efcf94"/><path d="M12 17H18" stroke="#fff" stroke-width="2"/>`;
      case 'M14': return `<path d="M6 52H94" stroke="#e2e8ec" stroke-width="5" stroke-linecap="round"/><path d="M9 20H57V45H9Z" fill="#f9fcff" stroke="#7596ac" stroke-width="1.5"/><path d="M57 28H75L85 39V45H57Z" fill="#87b4c6" stroke="#7596ac" stroke-width="1.5"/><path d="M62 31H73L79 38H62Z" fill="#e0f3fa"/><path d="M9 36H57" stroke="#e7b879" stroke-width="5"/><path d="M32 24V33M27.5 28.5H36.5" stroke="#77a9bd" stroke-width="3"/><circle cx="22" cy="46" r="6" fill="#647d94"/><circle cx="71" cy="46" r="6" fill="#647d94"/><circle cx="22" cy="46" r="2.5" fill="#d4e1eb"/><circle cx="71" cy="46" r="2.5" fill="#d4e1eb"/><rect class="am-beacon" x="61" y="23" width="10" height="5" rx="2" fill="#e9bc69"/><path d="M83 27V16M83 17Q88 11 94 17M79 10Q88 1 98 10" class="am-wireless"/><path d="M90 49 95 39 100 49Z" fill="#e6b57b"/>`;
      default: return '';
    }
  }

  // A deterministic little city, not a tiled map texture or geographic data.
  function building(x, y, w, h, tone = 0) {
    const roofs = ['#e7ded0', '#d7e0dd', '#d6dfeb', '#e2d7cc'];
    return `<g transform="translate(${x} ${y})"><rect x="3" y="4" width="${w}" height="${h}" rx="2" fill="#778d8530"/><path d="M0 ${h}H${w}V${h + 4}H0Z" fill="#aab9b3"/><rect width="${w}" height="${h}" rx="1.8" fill="${roofs[tone % 4]}" stroke="#b4c2ba" stroke-width=".65"/><path d="M3 3H${w - 3}" stroke="#fff" stroke-opacity=".65"/><path d="M${w * .35} 4V${h - 3}M${w * .7} 4V${h - 3}" stroke="#acbdbd" stroke-width="2" stroke-dasharray="2 3"/></g>`;
  }

  function canopy(x, y, r = 4, tone = 0) {
    return `<g><ellipse cx="${x + 1}" cy="${y + 2}" rx="${r + 1}" ry="${r}" fill="#496f4b16"/><circle cx="${x}" cy="${y}" r="${r}" fill="${['#96b991', '#adc897', '#81ae95'][tone % 3]}"/><circle cx="${x - 1}" cy="${y - 1}" r="${r * .55}" fill="#d0dfa7" opacity=".5"/></g>`;
  }

  function sceneryArtwork(geometry, index) {
    let result = '';
    const coordinates = geometry.path.match(/-?\d+(?:\.\d+)?/g).map(Number);
    const xs = coordinates.filter((_, i) => i % 2 === 0);
    const ys = coordinates.filter((_, i) => i % 2 === 1);
    const bounds = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    for (let row = 0; row < 14; row++) {
      for (let col = 0; col < 22; col++) {
        const seed = (row * 17 + col * 31 + index * 13) % 23;
        const x = col * 47 + 7 + (row % 2) * 12;
        const y = row * 45 + 18;
        if (x + 38 < bounds[0] || x > bounds[2] || y + 38 < bounds[1] || y > bounds[3]) continue;
        if (geometry.slots.some(([sx, sy]) => Math.abs(x + 13 - sx) < 56 && Math.abs(y + 9 - sy) < 42)) continue;
        if (seed % 5 === 0) {
          result += `<path d="M${x} ${y}q13-7 27 1l-2 20q-13 6-27-1Z" fill="#d5e4c7"/>`;
          result += canopy(x + 6, y + 7, 5, seed) + canopy(x + 20, y + 14, 6, seed + 1);
        } else {
          result += building(x, y, 16 + seed % 13, 10 + seed % 9, seed);
          if (seed % 3 === 0) result += building(x + 4, y + 24, 22, 8, seed + 1);
          result += canopy(x + 34, y + 9, 3.5, seed);
        }
      }
    }
    return result;
  }

  function urbanArtwork(id) {
    if (id === 'M1') return '<path d="M9 51H91" stroke="#bbd3cc" stroke-width="8" stroke-linecap="round"/><path d="M28 49V14H72V49" fill="#cde6e5" fill-opacity=".7" stroke="#557f84" stroke-width="2"/><path d="M20 14 29 7H78L72 14Z" fill="#4f939c"/><path d="M48 15V45M29 32H72M34 45H65" stroke="#71969b" stroke-width="2"/><rect x="78" y="16" width="14" height="12" rx="2" fill="#176a88"/><path d="M85 28V49M82 21H88M82 24H88" stroke="#dbf6f0" stroke-width="1.5"/>';
    if (id === 'M3') return '<path d="M8 48H92" stroke="#bfccdb" stroke-width="10" stroke-linecap="round"/><path d="M18 42V20M49 42V17M82 42V20" stroke="#7188aa" stroke-width="3"/><path d="M7 22Q50-2 94 22L89 27Q50 11 12 27Z" fill="#6686bb" stroke="#4a6c9b"/><path d="M17 41H82" stroke="#f4f8fc" stroke-width="5"/><rect x="37" y="24" width="27" height="12" rx="3" fill="#325f9e"/><text x="50.5" y="33" font-size="8" text-anchor="middle" fill="white" font-weight="700">LRT</text>';
    if (id === 'M12') return '<ellipse cx="50" cy="52" rx="39" ry="9" fill="#d0dfdb"/><path d="M34 15 41 11H68V52H34Z" fill="#608c99"/><rect x="37" y="16" width="26" height="34" rx="2" fill="#e9f5ef"/><rect x="41" y="21" width="18" height="19" rx="2" fill="#8abbb7"/><path d="M46 46H55" stroke="#557d87" stroke-width="2"/><g class="am-dialog"><path d="M53 1H83V20H72L65 26V20H53Z" fill="#347f87"/><path d="M59 10 65 15 76 6" fill="none" stroke="#e6fbef" stroke-width="2"/></g><circle cx="21" cy="30" r="5" fill="#cfab87"/><path d="M20 36V45M20 39 29 41M20 45 15 55M20 45 24 55" stroke="#6a779d" stroke-width="4" stroke-linecap="round"/>';
    return artwork(id);
  }

  /**
   * Offline, presentation-only city map. Scores come verbatim from baseline/report.districts[].score_after.
   * update({ selections, activeDistrict, report, viewMode, layer, activeMeasure, motionPaused, preview })
   * preserves project nodes, site allocations and running CSS animations. Preview never reserves a site.
   * All selections remain owned by the caller; interaction only invokes the supplied callbacks.
   * zoomBy is relative to the current centre (1..3); panBy receives screen-pixel deltas.
   * focusDistrict(null) resets the camera. Keyboard focus reveals clipped objects without selecting them.
   */
  window.createAstanaMap = function createAstanaMap(container, config, callbacks = {}) {
    const uid = `astana-map-${++mapSequence}`;
    const alreadyScoped = container.classList.contains('astana-map');
    container.classList.add('astana-map');
    const svg = element('svg', {
      class: 'am-svg', viewBox: CITY_VIEW, preserveAspectRatio: 'xMidYMid meet',
      role: 'group', 'aria-labelledby': `${uid}-title ${uid}-description`,
    });
    svg.innerHTML = `<title id="${uid}-title">Интерактивная карта Астаны</title>
      <desc id="${uid}-description">Условный город: пять районов, кварталы и река Есиль. Выберите район или проект клавишей Enter или пробелом. После приближения карту можно перетаскивать мышью или двигать стрелками. Все маршруты и размещение объектов схематичны.</desc>
      <defs>
        <linearGradient id="${uid}-water" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#83bbc8"/><stop offset=".5" stop-color="#a7d4dc"/><stop offset="1" stop-color="#7bb6ca"/></linearGradient>
        <pattern id="${uid}-dots" width="20" height="20" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".8" fill="#dce5e5"/></pattern>
        <g id="${uid}-avenues" fill="none" stroke-linecap="round">
          <path d="M19 217 395 119 710 211 992 268M98 34 213 594M315 23 344 600M549 24 501 311 605 606M840 98 784 574M22 453 464 426 977 513" stroke="#dce4e9" stroke-width="17"/>
          <path d="M19 217 395 119 710 211 992 268M98 34 213 594M315 23 344 600M549 24 501 311 605 606M840 98 784 574M22 453 464 426 977 513" stroke="#fff" stroke-width="11"/>
          <path d="M19 217 395 119 710 211 992 268M98 34 213 594M315 23 344 600M549 24 501 311 605 606M840 98 784 574M22 453 464 426 977 513" stroke="#dce5ed" stroke-width="1" stroke-dasharray="4 7"/>
        </g>
      </defs>
      <g class="am-backdrop" aria-hidden="true">
          <rect x="-1000" y="-1000" width="3000" height="2500" fill="#f1f4eb"/><rect width="1000" height="660" fill="url(#${uid}-dots)"/>
        <path d="M0 78Q33 53 45 97L31 237 0 258ZM0 510Q29 481 46 529L77 620H0ZM849 0Q800 65 929 114L1000 133V0Z" fill="#e8f0e6"/>
        <path d="M34 38H130M34 38V51M963 576V591H887" fill="none" stroke="#c8d6d4" stroke-width="1.5"/>
        <text x="45" y="28" class="am-map-caption">АСТАНА / ГОРОД ВАШИХ РЕШЕНИЙ</text>
        <path d="M46 625H954" stroke="#ccd8cf"/>
        <text x="46" y="646" class="am-map-note">СХЕМА · НЕ ГЕОГРАФИЧЕСКАЯ КАРТА</text>
        <text x="954" y="646" text-anchor="end" class="am-map-note">5 РАЙОНОВ · ОДИН ГОРОД</text>
      </g>`;
    const defs = svg.querySelector('defs');
    const districtsLayer = element('g', { class: 'am-districts' });
    const districtNodes = new Map();
    const districtConfig = new Map(config.districts.map((district) => [district.id, district]));
    const measures = new Map(config.measures.map((measure) => [measure.id, measure]));
    const allocations = new Map();

    Object.entries(GEOMETRY).forEach(([id, geometry], index) => {
      const district = districtConfig.get(id);
      if (!district) return;
      const clip = element('clipPath', { id: `${uid}-${id}-clip` });
      clip.append(element('path', { d: geometry.path }));
      defs.append(clip);
      const group = element('g', {
        class: 'am-district', 'data-map-district': id, role: 'button', tabindex: 0,
        'aria-pressed': 'false', 'aria-label': district.name,
      });
      group.append(element('path', { class: 'am-district-area', d: geometry.path }));
      const scenery = element('g', {
        class: 'am-district-scenery', 'clip-path': `url(#${uid}-${id}-clip)`, 'aria-hidden': 'true',
      });
      const blocks = element('g', { class: 'am-city-blocks' });
      blocks.innerHTML = sceneryArtwork(geometry, index);
      scenery.append(blocks);
      scenery.append(element('use', { href: `#${uid}-avenues` }));
      const sites = geometry.slots.map(([sx, sy], slot) => {
        const site = element('g', { class: 'am-existing-site', 'data-site-slot': slot, transform: `translate(${sx - 32} ${sy - 18})` });
        site.innerHTML = `<path d="M-7 2 16-9 59-4 68 22 54 39 6 37Z" fill="#e1e8d6"/>${building(0, 0, 22, 13, index + slot)}${building(30, 6, 26, 17, slot)}${building(8, 24, 24, 9, index)}${canopy(47, 32, 6, slot)}${canopy(-3, 25, 5, index)}`;
        scenery.append(site);
        return site;
      });
      group.append(scenery, element('path', { class: 'am-district-border', d: geometry.path }));
      const [x, y] = geometry.label;
      const label = element('g', { class: 'am-district-label', transform: `translate(${x} ${y})`, 'aria-hidden': 'true' });
      label.append(element('path', { class: 'am-label-accent', d: 'M-12-15V22' }));
      label.append(element('text', { class: 'am-district-name', x: 0, y: 0 }, district.name));
      const score = element('text', { class: 'am-district-score', x: 0, y: 20 });
      const badge = element('g', { class: 'am-count-badge', transform: 'translate(137 -7)' });
      badge.append(element('circle', { r: 13 }));
      const count = element('text', { 'text-anchor': 'middle', y: 4 }, '0');
      badge.append(count);
      label.append(score, badge);
      group.append(label);
      districtsLayer.append(group);
      districtNodes.set(id, { group, score, badge, count, sites });
      allocations.set(id, new Map());
    });
    svg.append(districtsLayer);

    const landmarks = element('g', { class: 'am-landmarks', 'aria-hidden': 'true' });
    landmarks.innerHTML = `<path d="${RIVER_PATH}" class="am-river-bank"/>
      <path d="${RIVER_PATH}" class="am-river-promenade"/>
      <path d="${RIVER_PATH}" class="am-river" style="stroke:url(#${uid}-water)"/>
      <path d="${RIVER_PATH}" class="am-river-glint"/>
      <g class="am-bridges"><path d="M167 277 183 322M326 300 339 361M475 281 460 341M719 344 749 428"/><path d="M167 277 183 322M326 300 339 361M475 281 460 341M719 344 749 428"/></g>
      <text x="381" y="322" transform="rotate(-12 381 322)" class="am-river-name">ЕСІЛ / ЕСИЛЬ</text>
      <g transform="translate(397 500)">
        <ellipse cy="31" rx="37" ry="9" fill="#d9e4e0"/><path d="M-34 27Q-9 8 7-28 13 3 33 27Z" fill="#e8eef6" stroke="#99aec7" stroke-width="1.5"/>
        <path d="M7-28-17 27M7-28-2 28M7-28 14 28M-29 23H29M-20 15H23M-12 6H18" fill="none" stroke="#c1cfde" stroke-width="1.2"/>
        <path d="M7-28 8-37" stroke="#869dbb" stroke-width="1.5"/><path d="M-35 28H34" stroke="#99adc7" stroke-width="3" stroke-linecap="round"/>
        <text y="50" text-anchor="middle" class="am-landmark-label">Хан Шатыр</text>
      </g>
      <g transform="translate(828 526)">
        <ellipse cy="31" rx="28" ry="8" fill="#dce6e0"/><path d="M-18 27H18M-12 22H12" stroke="#bcc7cf" stroke-width="4" stroke-linecap="round"/>
        <path d="M-5 21-12-18M5 21 12-18M0 21V-19M-8 8H8M-10-4H10" fill="none" stroke="#91a7bc" stroke-width="2"/>
        <circle cy="-27" r="14" fill="#dcc58c" stroke="#b99e65" stroke-width="1.5"/><path d="M-12-27H12M-10-33H10M-10-21H10M0-41Q-14-27 0-13M0-41Q14-27 0-13" fill="none" stroke="#eee0b9" stroke-width="1"/>
        <path d="M-7-17-4-8M7-17 4-8" stroke="#91a7bc" stroke-width="2"/><text y="52" text-anchor="middle" class="am-landmark-label">Байтерек</text>
      </g>
      <g transform="translate(946 65)"><text y="-16" text-anchor="middle" class="am-compass-label">С</text><path d="M0-9 7 13 0 8-7 13Z" fill="#94aac0"/><path d="M0-9V8L-7 13Z" fill="#d1dde7"/></g>
      <g class="am-waterfront-garden">${[[52, 291], [68, 288], [92, 289], [112, 289], [218, 304], [237, 310], [269, 315], [285, 317], [534, 324], [553, 335], [575, 343], [613, 365], [634, 364], [688, 329], [709, 332], [789, 439], [811, 446], [838, 449], [879, 450], [960, 465]].map(([x, y], i) => canopy(x, y, 4.5 + i % 2, i)).join('')}</g>
      <g transform="translate(249 320) rotate(17)"><path d="M-9 0Q0-7 10 0Q0 5-9 0Z" fill="#f8fbef" stroke="#5a929f"/><path d="M0-1V-11L7-1Z" fill="#e7c890"/></g>
      <g transform="translate(585 364) rotate(14)"><path d="M-7 0H8L4 4H-4Z" fill="#f8fbef" stroke="#5a929f"/></g>
      <g transform="translate(676 83)"><ellipse cy="13" rx="21" ry="7" fill="#d7dfcf"/><path d="M-15 8V-13L0-21 15-13V8Z" fill="#dfd7c4" stroke="#aeb9af"/><path d="M-18-13 0-27 18-13Z" fill="#819c99"/><path d="M-9 7V-6H-3V7M3 7V-6H9V7" fill="#bad0d1"/><text y="30" text-anchor="middle" class="am-landmark-label">Старый город</text></g>`;
    svg.append(landmarks);
    const projectsLayer = element('g', { class: 'am-projects' });
    const previewLayer = element('g', { class: 'am-previews', 'aria-hidden': 'true' });
    svg.append(projectsLayer, landmarks, previewLayer);
    container.append(svg);

    let state = { selections: [], activeDistrict: null, report: null, viewMode: 'plan', layer: 'projects', activeMeasure: null, motionPaused: false, preview: null };
    let destroyed = false;
    const projects = new Map();
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const pausedAnimations = new Set();
    function syncMotion() {
      svg.classList.toggle('am-reduced-motion', motionQuery.matches);
      svg.classList.toggle('am-motion-paused', Boolean(state.motionPaused));
      svg.setAttribute('data-motion', motionQuery.matches ? 'reduced' : state.motionPaused ? 'paused' : 'running');
      const paused = state.motionPaused || state.viewMode === 'baseline';
      // Also respect a pause after an animation was scrubbed through the Web Animations API.
      svg.getAnimations({ subtree: true }).forEach((animation) => {
        if (paused && animation.playState === 'running') {
          animation.pause();
          animation.currentTime = animation.currentTime;
          pausedAnimations.add(animation);
        }
      });
      pausedAnimations.forEach((animation) => {
        if (animation.playState === 'idle') pausedAnimations.delete(animation);
        else if (!paused) { animation.play(); pausedAnimations.delete(animation); }
      });
    }
    syncMotion();
    motionQuery.addEventListener('change', syncMotion);

    let drag = null;
    let suppressClickUntil = 0;
    let viewport = { zoom: 1, cx: WIDTH / 2, cy: HEIGHT / 2, focusedDistrict: null };

    function select(event) {
      if (event.type === 'click' && performance.now() < suppressClickUntil) { event.preventDefault(); return; }
      if (event.type === 'keydown' && !['Enter', ' ', 'Spacebar'].includes(event.key)) return;
      if (event.type === 'keydown' && event.repeat) return;
      const project = event.target.closest('[data-map-project]');
      const district = event.target.closest('[data-map-district]');
      if (!project && !district) return;
      event.preventDefault();
      if (project) {
        const districtId = project.getAttribute('data-project-district');
        callbacks.onProjectSelect?.({
          measureId: project.getAttribute('data-map-project'),
          districtId: districtId === 'city' ? null : districtId,
        });
      } else {
        callbacks.onDistrictSelect?.(district.getAttribute('data-map-district'));
      }
    }
    svg.addEventListener('click', select);
    svg.addEventListener('keydown', select);

    function setViewport(next) {
      const zoom = Math.max(1, Math.min(3, next.zoom));
      const halfWidth = WIDTH / zoom / 2;
      const halfHeight = HEIGHT / zoom / 2;
      const cx = Math.max(halfWidth, Math.min(WIDTH - halfWidth, next.cx));
      const cy = Math.max(halfHeight, Math.min(HEIGHT - halfHeight, next.cy));
      const focusedDistrict = next.focusedDistrict || null;
      const changed = zoom !== viewport.zoom || focusedDistrict !== viewport.focusedDistrict;
      viewport = { zoom, cx, cy, focusedDistrict };
      svg.setAttribute('viewBox', `${cx - halfWidth} ${cy - halfHeight} ${halfWidth * 2} ${halfHeight * 2}`);
      svg.setAttribute('data-zoom', String(Number(zoom.toFixed(3))));
      svg.classList.toggle('am-zoomed', zoom > 1);
      if (focusedDistrict) svg.setAttribute('data-focused-district', focusedDistrict);
      else svg.removeAttribute('data-focused-district');
      // Report only semantic changes, after storing state, so toolbar updates cannot recurse.
      if (changed) callbacks.onViewportChange?.({ zoom, focusedDistrict });
    }

    function zoomBy(factor) {
      if (destroyed || !Number.isFinite(factor) || factor <= 0) return;
      setViewport({ ...viewport, zoom: viewport.zoom * factor, focusedDistrict: null });
    }

    // dx/dy are screen pixels: dragging moves the map in the same direction as the pointer.
    function panBy(dx, dy) {
      if (destroyed || !Number.isFinite(dx) || !Number.isFinite(dy) || viewport.zoom === 1) return;
      const rect = svg.getBoundingClientRect();
      const scale = Math.min(rect.width / (WIDTH / viewport.zoom), rect.height / (HEIGHT / viewport.zoom));
      if (!scale) return;
      setViewport({ ...viewport, cx: viewport.cx - dx / scale, cy: viewport.cy - dy / scale, focusedDistrict: null });
    }

    function pointerDown(event) {
      if (event.pointerType !== 'mouse' || event.button !== 0) return;
      suppressClickUntil = 0;
      drag = { id: event.pointerId, startX: event.clientX, startY: event.clientY, x: event.clientX, y: event.clientY, moved: false };
    }

    function pointerMove(event) {
      if (!drag || event.pointerId !== drag.id) return;
      if (!drag.moved && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 6) return;
      if (!drag.moved) {
        drag.moved = true;
        svg.setPointerCapture(event.pointerId);
        svg.classList.add('am-dragging');
      }
      event.preventDefault();
      panBy(event.clientX - drag.x, event.clientY - drag.y);
      drag.x = event.clientX;
      drag.y = event.clientY;
    }

    function pointerUp(event) {
      if (!drag || event.pointerId !== drag.id) return;
      if (drag.moved) suppressClickUntil = performance.now() + 500;
      drag = null;
      svg.classList.remove('am-dragging');
      if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    }

    function viewportKey(event) {
      if (event.ctrlKey || event.altKey || event.metaKey) return;
      const steps = { ArrowLeft: [55, 0], ArrowRight: [-55, 0], ArrowUp: [0, 55], ArrowDown: [0, -55] };
      if (steps[event.key] && viewport.zoom > 1) { event.preventDefault(); panBy(...steps[event.key]); }
      if (event.key === '+' || event.key === '=') { event.preventDefault(); zoomBy(1.25); }
      if (event.key === '-') { event.preventDefault(); zoomBy(.8); }
      if (event.key === '0') { event.preventDefault(); focusDistrict(null); }
    }

    function revealFocus(event) {
      if (viewport.zoom === 1) return;
      const project = event.target.closest('[data-map-project]');
      const district = event.target.closest('[data-map-district]');
      if (!project && !district) return;
      const frame = svg.getBoundingClientRect();
      const visible = (node) => {
        const box = node.getBoundingClientRect();
        return box.left >= frame.left + 3 && box.right <= frame.right - 3 && box.top >= frame.top + 3 && box.bottom <= frame.bottom - 3;
      };
      if (project) {
        const sites = [...project.querySelectorAll('.am-project-site')];
        if (sites.some(visible)) return;
        const target = sites.find((site) => site.closest('[data-object-district]').getAttribute('data-object-district') === state.activeDistrict) || sites[0];
        if (target) focusDistrict(target.closest('[data-object-district]').getAttribute('data-object-district'));
      } else if (!visible(district.querySelector('.am-district-area'))) {
        focusDistrict(district.getAttribute('data-map-district'));
      }
    }

    svg.addEventListener('pointerdown', pointerDown);
    svg.addEventListener('pointermove', pointerMove);
    svg.addEventListener('pointerup', pointerUp);
    svg.addEventListener('pointercancel', pointerUp);
    svg.addEventListener('lostpointercapture', pointerUp);
    svg.addEventListener('keydown', viewportKey);
    svg.addEventListener('focusin', revealFocus);

    function addRoute(placement, districtId, measureId) {
      const isTrain = measureId === 'M3';
      const pathData = GEOMETRY[districtId].route;
      const route = element('g', { class: `am-route ${isTrain ? 'am-route-lrt' : 'am-route-bus'}`, 'data-route-district': districtId, 'data-route-measure': measureId, 'clip-path': `url(#${uid}-${districtId}-clip)` });
      route.append(element('path', { class: 'am-route-halo', d: pathData }));
      const road = element('path', { class: 'am-route-road', d: pathData });
      route.append(road, element('path', { class: 'am-route-line', d: pathData }));
      if (isTrain) route.append(element('path', { class: 'am-route-sleepers', d: pathData }));
      placement.append(route);
      const length = road.getTotalLength();
      [.05, .3, .56, .8].forEach((fraction, index) => {
        const point = road.getPointAtLength(length * fraction);
        const stop = element('g', { class: 'am-route-stop', 'data-route-stop': index + 1, transform: `translate(${point.x} ${point.y})` });
        stop.append(element('title', {}, `${isTrain ? 'Станция ЛРТ' : 'Остановка автобуса'} ${index + 1} · условный маршрут`));
        stop.append(element('circle', { class: 'am-stop-platform', r: isTrain ? 6 : 5 }));
        stop.append(element('circle', { class: 'am-stop-core', r: 2.1 }));
        if (index === 0 || index === 2) stop.append(element('text', { class: 'am-stop-label', x: 8, y: -8 }, `${isTrain ? 'ЛРТ' : 'А'} ${index + 1}`));
        route.append(stop);
      });
      const moving = element('g', { class: `am-route-vehicle ${isTrain ? 'am-train' : 'am-bus'}`, 'data-route-vehicle': measureId });
      moving.style.offsetPath = `path("${pathData}")`;
      const body = element('g');
      body.innerHTML = vehicle(isTrain ? 'train' : 'bus');
      body.firstElementChild.removeAttribute('class');
      body.firstElementChild.setAttribute('transform', 'scale(.75)');
      moving.append(body);
      route.append(moving);
    }

    function addProject(key, selection, measure) {
      const citywide = measure.type === 'city';
      const affected = citywide ? [...districtNodes.keys()] : [selection.district_id];
      const location = citywide ? 'весь город, все пять районов' : districtConfig.get(selection.district_id)?.name;
      const group = element('g', {
        class: 'am-project', 'data-map-project': measure.id,
        'data-project-district': citywide ? 'city' : selection.district_id,
        'data-direction': measure.direction, tabindex: 0, role: 'button',
        'aria-label': `${measure.name} · ${location}`,
      });
      group.append(element('title', {}, `${measure.name} · ${location}`));
      // Routes sit below the other project sites, but belong to the same project group.
      if (measure.id === 'M1' || measure.id === 'M3') projectsLayer.prepend(group);
      else projectsLayer.append(group);
      affected.forEach((districtId) => {
        const geometry = GEOMETRY[districtId];
        const occupied = allocations.get(districtId);
        if (!geometry || !occupied) return;
        const taken = new Set(occupied.values());
        const slot = geometry.slots.findIndex((_, index) => !taken.has(index));
        if (slot < 0) return;
        occupied.set(key, slot);
        const [x, y] = geometry.slots[slot];
        const placement = element('g', {
          class: 'am-project-placement', 'data-object-district': districtId,
          'data-object-slot': slot, 'aria-hidden': 'true',
        });
        group.append(placement);
        if (measure.id === 'M1' || measure.id === 'M3') addRoute(placement, districtId, measure.id);
        const site = element('g', { class: 'am-project-site', transform: `translate(${x - 37} ${y - 25}) scale(.74)` });
        const entrance = element('g', { class: `am-project-enter${state.motionPaused || motionQuery.matches ? ' am-enter-static' : ''}` });
        entrance.append(element('path', { class: 'am-project-ground', d: 'M-4 26 9 10 73 7 101 27 102 48 84 59 14 60-5 48Z' }));
        entrance.append(element('path', { class: 'am-project-outline', d: 'M-8 22 7 2 74 0 106 23 108 53 87 65 11 66-11 50Z' }));
        entrance.append(element('path', { class: 'am-project-hit', d: 'M-10-13H109V85H-10Z' }));
        const picture = element('g', { class: `am-art am-art-${measure.id.toLowerCase()}` });
        picture.innerHTML = urbanArtwork(measure.id);
        entrance.append(picture);
        entrance.append(element('text', { class: 'am-project-caption', x: 50, y: 78, 'text-anchor': 'middle' }, SHORT_NAMES[measure.id] || measure.id));
        entrance.append(element('rect', { class: 'am-project-code-plate', x: -6, y: -14, width: 28, height: 17, rx: 5 }));
        entrance.append(element('text', { class: 'am-project-code', x: 8, y: -1.5, 'text-anchor': 'middle' }, measure.id));
        site.append(entrance);
        placement.append(site);
        const caption = entrance.querySelector('.am-project-caption');
        if (caption.getComputedTextLength() > 108) {
          caption.setAttribute('textLength', '108');
          caption.setAttribute('lengthAdjust', 'spacingAndGlyphs');
        }
      });
      projects.set(key, { group, affected, location: citywide ? 'city' : selection.district_id });
    }

    let previewSignature = '';
    function updatePreview() {
      const measure = measures.get(state.preview?.measure_id);
      const affected = measure?.type === 'city' ? [...districtNodes.keys()] : [state.preview?.district_id];
      const available = measure && !projects.has(measure.id) && affected.every((id) => allocations.has(id) && allocations.get(id).size < 5) ? affected : [];
      const slots = available.map((id) => {
        const taken = new Set(allocations.get(id).values());
        return [id, GEOMETRY[id].slots.findIndex((_, index) => !taken.has(index))];
      });
      const signature = JSON.stringify([measure?.id, slots]);
      if (signature === previewSignature) return;
      previewSignature = signature;
      previewLayer.replaceChildren();
      if (!slots.length) return;
      const group = element('g', { class: 'am-preview', 'data-map-preview': measure.id });
      slots.forEach(([id, slot]) => {
        const [x, y] = GEOMETRY[id].slots[slot];
        const site = element('g', { class: 'am-preview-placement', 'data-preview-district': id, 'data-preview-slot': slot, transform: `translate(${x - 37} ${y - 25}) scale(.74)` });
        site.append(element('path', { class: 'am-preview-ground', d: 'M-6 17 10 3 78 3 105 21 103 53 83 64 8 64-7 45Z' }));
        site.append(element('path', { class: 'am-preview-grid', d: 'M4 38 80 10M14 53 96 24M37 61 100 38M24 7 10 49M49 5 29 62M77 6 57 62M96 22 81 62' }));
        site.append(element('text', { class: 'am-preview-code', x: 50, y: 37, 'text-anchor': 'middle' }, measure.id));
        site.append(element('title', {}, `Эскиз · ${measure.name} · ${districtConfig.get(id).name}`));
        site.append(element('text', { class: 'am-preview-caption', x: 50, y: 79, 'text-anchor': 'middle' }, 'Эскиз'));
        group.append(site);
      });
      previewLayer.append(group);
    }

    function update(next = {}) {
      if (destroyed) return;
      state = { ...state, ...next };
      const desired = new Map();
      (state.selections || []).forEach((selection) => {
        const measure = measures.get(selection.measure_id);
        if (!measure) return;
        const location = measure.type === 'city' ? 'city' : selection.district_id;
        if (location !== 'city' && !districtNodes.has(location)) return;
        desired.set(measure.id, { selection, measure, location });
      });
      projects.forEach(({ group, affected, location }, key) => {
        if (desired.get(key)?.location === location) return;
        if (group.contains(document.activeElement)) {
          const districtId = state.activeDistrict || affected[0];
          districtNodes.get(districtId)?.group.focus({ preventScroll: true });
        }
        group.remove();
        affected.forEach((id) => allocations.get(id)?.delete(key));
        projects.delete(key);
      });
      desired.forEach(({ selection, measure }, key) => {
        if (!projects.has(key)) addProject(key, selection, measure);
      });
      const isBaseline = state.viewMode === 'baseline';
      const report = isBaseline ? null : state.report;
      const scores = new Map((report || config.baseline)?.districts?.map((district) => [district.id, district]) || []);
      districtNodes.forEach(({ group, score, badge, count, sites }, id) => {
        const item = scores.get(id);
        const value = item?.score_after;
        const formatted = Number.isFinite(value) ? value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';
        const mode = report ? 'Расчёт' : 'Исходно';
        const delta = report && Number.isFinite(item?.score_delta) ? ` · ${item.score_delta >= 0 ? '+' : '−'}${Math.abs(item.score_delta).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '';
        const selectedCount = isBaseline ? 0 : allocations.get(id).size;
        const occupied = new Set(isBaseline ? [] : allocations.get(id).values());
        sites.forEach((site, slot) => site.classList.toggle('am-site-occupied', occupied.has(slot)));
        score.textContent = `${mode} ${formatted}${delta}`;
        count.textContent = String(selectedCount);
        badge.classList.toggle('am-count-empty', selectedCount === 0);
        group.setAttribute('aria-pressed', String(state.activeDistrict === id));
        group.setAttribute('data-score', Number.isFinite(value) ? String(value) : '');
        group.setAttribute('data-score-delta', report && Number.isFinite(item?.score_delta) ? String(item.score_delta) : '');
        group.setAttribute('data-score-band', !Number.isFinite(value) ? 'unknown' : value < 40 ? 'critical' : value < 60 ? 'developing' : 'strong');
        group.setAttribute('aria-label', `${districtConfig.get(id).name}. ${mode}: ${formatted}${delta}. Мер в районе: ${selectedCount}. Выбрать район.`);
      });
      projects.forEach(({ group, affected }, key) => {
        if (isBaseline && group.contains(document.activeElement)) districtNodes.get(affected[0])?.group.focus({ preventScroll: true });
        const active = state.activeMeasure === key;
        group.classList.toggle('am-project-active', active);
        group.setAttribute('aria-pressed', String(active));
        group.setAttribute('tabindex', isBaseline ? '-1' : '0');
      });
      projectsLayer.setAttribute('aria-hidden', String(isBaseline));
      svg.setAttribute('data-score-source', report ? 'report' : 'baseline');
      svg.setAttribute('data-view-mode', isBaseline ? 'baseline' : 'plan');
      svg.setAttribute('data-layer', state.layer === 'scores' ? 'scores' : 'projects');
      syncMotion();
      updatePreview();
    }

    function focusDistrict(districtId) {
      if (destroyed) return;
      const geometry = districtNodes.has(districtId) ? GEOMETRY[districtId] : null;
      setViewport(geometry ? { zoom: geometry.zoom, cx: geometry.center[0], cy: geometry.center[1], focusedDistrict: districtId } : { zoom: 1, cx: WIDTH / 2, cy: HEIGHT / 2, focusedDistrict: null });
    }

    function destroy() {
      if (destroyed) return;
      destroyed = true;
      svg.removeEventListener('click', select);
      svg.removeEventListener('keydown', select);
      svg.removeEventListener('pointerdown', pointerDown);
      svg.removeEventListener('pointermove', pointerMove);
      svg.removeEventListener('pointerup', pointerUp);
      svg.removeEventListener('pointercancel', pointerUp);
      svg.removeEventListener('lostpointercapture', pointerUp);
      svg.removeEventListener('keydown', viewportKey);
      svg.removeEventListener('focusin', revealFocus);
      motionQuery.removeEventListener('change', syncMotion);
      projects.clear();
      pausedAnimations.clear();
      allocations.clear();
      svg.remove();
      if (!alreadyScoped) container.classList.remove('astana-map');
    }

    update();
    svg.setAttribute('data-zoom', '1');
    return { update, focusDistrict, zoomBy, panBy, destroy };
  };
})();
