# DNF Open API 응답 레퍼런스

> Base URL: `https://api.neople.co.kr/df`
> 이미지 API: `https://img-api.neople.co.kr/df`
> 레퍼런스 캐릭터: 카시야스 / 김철완 (`ab590098566252dad7fe024ab17f5fcc`)
> 레퍼런스 아이템: 형상화된 요기의 단서 (`f9941d3fa0b8253bb0b2567a29b1299f`)
> 조회일: 2026-03-09

---

## 01. 서버 정보

`GET /df/servers`

```json
{
  "rows": [
    { "serverId": "cain", "serverName": "카인" },
    { "serverId": "diregie", "serverName": "디레지에" },
    { "serverId": "siroco", "serverName": "시로코" },
    { "serverId": "prey", "serverName": "프레이" },
    { "serverId": "casillas", "serverName": "카시야스" },
    { "serverId": "hilder", "serverName": "힐더" },
    { "serverId": "anton", "serverName": "안톤" },
    { "serverId": "bakal", "serverName": "바칼" }
  ]
}
```

---

## 02. 캐릭터 검색

`GET /df/servers/{serverId}/characters`

```json
{
  "rows": [
    {
      "serverId": "casillas",
      "characterId": "ab590098566252dad7fe024ab17f5fcc",
      "characterName": "김철완",
      "level": 115,
      "jobId": "a7a059ebe9e6054c0644b40ef316d6e9",
      "jobGrowId": "37495b941da3b1661bc900e68ef3b2c6",
      "jobName": "격투가(여)",
      "jobGrowName": "眞 넨마스터",
      "fame": 83413
    }
  ]
}
```

> 캐릭터 이미지 URL: `https://img-api.neople.co.kr/df/servers/{serverId}/characters/{characterId}?zoom={1~3}`

---

## 03. 캐릭터 기본 정보 조회

`GET /df/servers/{serverId}/characters/{characterId}`

```json
{
  "serverId": "casillas",
  "characterId": "ab590098566252dad7fe024ab17f5fcc",
  "characterName": "김철완",
  "level": 115,
  "jobId": "a7a059ebe9e6054c0644b40ef316d6e9",
  "jobGrowId": "37495b941da3b1661bc900e68ef3b2c6",
  "jobName": "격투가(여)",
  "jobGrowName": "眞 넨마스터",
  "fame": 83413,
  "adventureName": "영정은날막지못해",
  "guildId": "ea891c34385b7b26712f4d5ca8927d87",
  "guildName": "SBH마스터즈"
}
```

> 기본 정보에는 `adventureName`, `guildId`, `guildName`이 추가됨 (검색 결과에는 없음)

---

## 04. 캐릭터 타임라인 정보 조회

`GET /df/servers/{serverId}/characters/{characterId}/timeline`

```json
{
  "serverId": "casillas",
  "characterId": "ab590098566252dad7fe024ab17f5fcc",
  "characterName": "김철완",
  "level": 115,
  "jobId": "...",
  "jobGrowId": "...",
  "jobName": "격투가(여)",
  "jobGrowName": "眞 넨마스터",
  "fame": 83413,
  "adventureName": "영정은날막지못해",
  "guildId": "...",
  "guildName": "SBH마스터즈",
  "timeline": {
    "date": {
      "start": "2025-01-01 00:00",
      "end": "2025-03-09 23:59"
    },
    "next": null,
    "rows": [
      {
        "code": 505,
        "name": "아이템 획득(에픽)",
        "date": "2025-01-15 14:23",
        "data": {
          "itemId": "...",
          "itemName": "...",
          "itemRarity": "에픽",
          "channelName": "...",
          "channelNo": 1,
          "dungeonName": "..."
        }
      }
    ]
  }
}
```

> `next`가 null이 아니면 다음 페이지 존재. `next` 값을 쿼리 파라미터로 전달하여 페이징.
> 기간 최대 90일. `code` 다중 입력 시 콤마 구분 (예: `505,504,507,508,513`)

### 타임라인 코드 (주요)

| 코드 | 설명 |
|------|------|
| 201 | 레이드 클리어 |
| 504 | 아이템 획득(유니크) |
| 505 | 아이템 획득(에픽) |
| 507 | 아이템 획득(레전더리) |
| 508 | 아이템 획득(신화) |
| 513 | 아이템 획득(태초) |

---

## 05. 캐릭터 능력치 정보 조회

`GET /df/servers/{serverId}/characters/{characterId}/status`

```json
{
  "serverId": "...",
  "characterId": "...",
  "characterName": "김철완",
  "...": "캐릭터 공통 필드 생략",
  "buff": [
    {
      "name": "모험단 버프",
      "level": 40,
      "status": [
        { "name": "힘", "value": 290 },
        { "name": "지능", "value": 290 },
        { "name": "체력", "value": 290 },
        { "name": "정신력", "value": 290 }
      ]
    },
    {
      "name": "무제한 길드능력치",
      "status": [
        { "name": "힘", "value": 60 }
      ]
    }
  ],
  "status": [
    { "name": "HP", "value": 159673 },
    { "name": "MP", "value": 134471 },
    { "name": "힘", "value": 4550 },
    { "name": "지능", "value": 6948 },
    { "name": "모험가 명성", "value": 83413 },
    { "name": "공격력 증가", "value": 71566.6 },
    { "name": "최종 데미지 증가", "value": 2947566.5 },
    { "name": "쿨타임 감소", "value": 27.8 }
  ]
}
```

> `status` 배열에 약 70개 이상의 능력치 포함 (공격, 방어, 속성, 상태이상 내성 등)
> 최근 1년 이내 접속 캐릭터만 조회 가능

---

## 06. 캐릭터 장착 장비 조회

`GET /df/servers/{serverId}/characters/{characterId}/equip/equipment`

```json
{
  "...": "캐릭터 공통 필드",
  "equipment": [
    {
      "slotId": "WEAPON",
      "slotName": "무기",
      "itemId": "...",
      "itemName": "리리스, 디 이블",
      "itemTypeId": "...",
      "itemType": "무기",
      "itemTypeDetailId": "...",
      "itemTypeDetail": "클로",
      "itemAvailableLevel": 115,
      "itemRarity": "태초",
      "setItemId": null,
      "setItemName": null,
      "reinforce": 13,
      "itemGradeName": "최상급",
      "enchant": {
        "status": [
          { "name": "모든 속성 강화", "value": 15 },
          { "name": "물리 공격력", "value": 30 }
        ]
      },
      "amplificationName": null,
      "refine": 3,
      "engrave": {
        "itemId": "...",
        "itemName": "디레지에 레이드 : 이명 각인권"
      },
      "tune": [
        {
          "level": 3,
          "status": [
            { "name": "최종 데미지", "value": "430.5%" }
          ]
        }
      ]
    },
    {
      "slotId": "JACKET",
      "slotName": "상의",
      "itemId": "...",
      "itemName": "잠식 : 칠흑의 정화 상의",
      "itemRarity": "에픽",
      "setItemId": "11f7d203a05ea6f13300c0facb39f11e",
      "setItemName": "칠흑의 정화 세트",
      "reinforce": 10,
      "itemGradeName": "최상급",
      "amplificationName": "차원의 지능",
      "fusionOption": {
        "options": [
          {
            "buff": 3360,
            "explain": "최종 데미지 11% 증가\n스킬 쿨타임 4% 감소 ...",
            "explainDetail": "...",
            "buffExplain": "버프력 3360",
            "buffExplainDetail": "버프력 3360"
          }
        ]
      },
      "upgradeInfo": {
        "itemId": "...",
        "itemName": "욕망 : 잃어버린 영혼",
        "itemRarity": "에픽"
      },
      "tune": [
        { "level": 3, "setPoint": 265 }
      ]
    },
    {
      "slotId": "SUPPORT",
      "slotName": "보조장비",
      "...": "기본 장비 필드",
      "exaltedInfo": {
        "damage": "38.4%",
        "buff": 11220,
        "explain": "<생명의 불꽃을 꺼뜨리는 자>..."
      },
      "potency": {
        "value": 40,
        "damage": "4%",
        "buff": 1520
      }
    }
  ],
  "setItemInfo": [
    {
      "setItemId": "...",
      "setItemName": "칠흑의 정화 : 균형 세트",
      "setItemRarityName": "태초",
      "active": {
        "explain": "정화와 타락의 조화를 이뤄...",
        "explainDetail": "...",
        "status": [
          { "name": "모험가 명성", "value": 23000 },
          { "name": "버프력", "value": 50400 },
          { "name": "최종 데미지", "value": "301.1%" },
          { "name": "스킬 쿨타임 감소", "value": "-30%" }
        ],
        "setPoint": {
          "current": 2550,
          "min": 2550,
          "max": 2550
        }
      },
      "slotInfo": [
        {
          "itemNo": "...",
          "slotId": "JACKET",
          "slotName": "상의",
          "itemRarity": "에픽"
        },
        {
          "itemNo": "...",
          "slotId": "PANTS",
          "slotName": "하의",
          "itemRarity": "에픽",
          "fusionStone": true
        }
      ]
    }
  ]
}
```

### 장비 slotId 목록

| slotId | slotName |
|--------|----------|
| WEAPON | 무기 |
| TITLE | 칭호 |
| JACKET | 상의 |
| SHOULDER | 머리어깨 |
| PANTS | 하의 |
| SHOES | 신발 |
| WAIST | 벨트 |
| AMULET | 목걸이 |
| WRIST | 팔찌 |
| RING | 반지 |
| SUPPORT | 보조장비 |
| MAGIC_STON | 마법석 |
| EARRING | 귀걸이 |

### 장비 선택적 필드

| 필드 | 설명 | 조건 |
|------|------|------|
| `enchant` | 인챈트 정보 | 인챈트 적용 시 |
| `amplificationName` | 증폭 이름 | 증폭 적용 시 (null이면 강화) |
| `engrave` | 각인 정보 | 무기 각인 시 |
| `fusionOption` | 융합 옵션 | 융합 적용 시 |
| `upgradeInfo` | 업그레이드 정보 | 업그레이드 시 (setItemId/setPoint 포함 가능) |
| `tune` | 튜닝 정보 | 튜닝 적용 시 (level, setPoint, status, upgrade 등) |
| `exaltedInfo` | 고양(승격) 정보 | 태초 보조장비 등 |
| `potency` | 잠재력 | 잠재력 적용 시 (value, damage, buff) |

---

## 07. 캐릭터 장착 아바타 조회

`GET /df/servers/{serverId}/characters/{characterId}/equip/avatar`

```json
{
  "...": "캐릭터 공통 필드",
  "avatar": [
    {
      "slotId": "HAIR",
      "slotName": "머리 아바타",
      "itemId": "b01acffc6c45a4dda027af4a8fe57c6b",
      "itemName": "레어 머리 클론 아바타",
      "itemRarity": "레어",
      "clone": {
        "itemId": "eaf30a032a911e88133f190244fd331b",
        "itemName": "레이스 롱웨이브 머리"
      },
      "optionAbility": "지능 55 증가",
      "emblems": [
        {
          "slotNo": 1,
          "slotColor": "붉은빛",
          "itemId": "4b068f14e58d828d938b9bc269963690",
          "itemName": "찬란한 붉은빛 엠블렘[지능]",
          "itemRarity": "유니크"
        }
      ]
    }
  ]
}
```

### 아바타 slotId 목록

| slotId | slotName |
|--------|----------|
| HEADGEAR | 모자 아바타 |
| HAIR | 머리 아바타 |
| FACE | 얼굴 아바타 |
| JACKET | 상의 아바타 |
| PANTS | 하의 아바타 |
| SHOES | 신발 아바타 |
| BREAST | 목가슴 아바타 |
| WAIST | 허리 아바타 |
| SKIN | 스킨 아바타 |
| AURORA | 오라 아바타 |
| WEAPON | 무기 아바타 |
| AURA_SKIN | 오라 스킨 아바타 |

---

## 08. 캐릭터 장착 크리쳐 조회

`GET /df/servers/{serverId}/characters/{characterId}/equip/creature`

```json
{
  "...": "캐릭터 공통 필드",
  "creature": {
    "itemId": "...",
    "itemName": "운명을 담는 재단사 플래티넘[80Lv]",
    "itemRarity": "레어",
    "clone": { "itemId": null, "itemName": null },
    "artifact": [
      {
        "slotColor": "RED",
        "itemId": "...",
        "itemName": "눈부신 황혼의 공명",
        "itemAvailableLevel": 0,
        "itemRarity": "유니크"
      },
      { "slotColor": "BLUE", "...": "..." },
      { "slotColor": "GREEN", "...": "..." }
    ]
  }
}
```

---

## 09. 캐릭터 장착 휘장 조회

`GET /df/servers/{serverId}/characters/{characterId}/equip/flag`

```json
{
  "...": "캐릭터 공통 필드",
  "flag": {
    "itemId": "...",
    "itemName": "영광스러운 승리의 휘장",
    "itemRarity": "에픽",
    "reinforce": 10,
    "reinforceStatus": [
      { "name": "공격력 증가", "value": 389.6 },
      { "name": "버프력", "value": 473 },
      { "name": "모험가 명성", "value": 236 }
    ],
    "gems": [
      {
        "slotNo": 1,
        "itemId": "...",
        "itemName": "찬란한 용기의 젬",
        "itemRarity": "레전더리"
      }
    ]
  }
}
```

---

## 10. 캐릭터 안개 융화 조회

`GET /df/servers/{serverId}/characters/{characterId}/equip/mist-assimilation`

```json
{
  "...": "캐릭터 공통 필드",
  "mistAssimilation": {
    "level": 30,
    "expRate": "100%",
    "status": [
      { "name": "최종 데미지", "value": "30%" },
      { "name": "버프력", "value": 4400 },
      { "name": "힘", "value": 250 },
      { "name": "모험가 명성", "value": 3000 }
    ]
  }
}
```

---

## 11. 캐릭터 스킬 스타일 조회

`GET /df/servers/{serverId}/characters/{characterId}/skill/style`

```json
{
  "...": "캐릭터 공통 필드",
  "skill": {
    "hash": "eJytx6FOAgEA...",
    "style": {
      "active": [
        {
          "skillId": "...",
          "name": "기옥탄",
          "level": 53,
          "requiredLevel": 15
        }
      ],
      "passive": [
        {
          "skillId": "...",
          "name": "기본기 숙련",
          "level": 115,
          "requiredLevel": 1
        }
      ],
      "evolution": [
        { "skillId": "...", "type": 2 }
      ],
      "enhancement": [
        { "skillId": "...", "type": 1 }
      ]
    }
  }
}
```

---

## 12. 캐릭터 버프 스킬 강화 장착 장비 조회

`GET /df/servers/{serverId}/characters/{characterId}/skill/buff/equip/equipment`

```json
{
  "...": "캐릭터 공통 필드",
  "skill": {
    "buff": {
      "skillInfo": {
        "skillId": "...",
        "name": "카이",
        "option": {
          "level": 20,
          "desc": "시전 범위 : {value1}px\n지속 시간 : {value2}초\n...",
          "values": ["450", "-", "61", "21"]
        }
      },
      "equipment": [
        {
          "slotId": "WEAPON",
          "slotName": "무기",
          "itemId": "...",
          "itemName": "짙은 심연의 편린 너클 : 카이",
          "itemAvailableLevel": 100,
          "itemRarity": "유니크",
          "reinforce": 0,
          "enchant": {
            "reinforceSkill": [
              {
                "jobId": "...",
                "jobName": "격투가(여)",
                "skills": [
                  { "skillId": "...", "name": "카이", "value": 2 }
                ]
              }
            ]
          }
        }
      ]
    }
  }
}
```

> 13번(버프 아바타), 14번(버프 크리쳐)도 동일 구조. `equipment` 대신 `avatar`, `creature` 키 사용.

---

## 15. 캐릭터 명성 검색

`GET /df/servers/{serverId}/characters-fame`

```json
{
  "fame": {
    "min": 87753,
    "max": 89753
  },
  "rows": [
    {
      "serverId": "casillas",
      "characterId": "...",
      "characterName": "야다몽",
      "level": 115,
      "jobId": "...",
      "jobName": "도적",
      "jobGrowId": "...",
      "jobGrowName": "眞 로그",
      "fame": 89753
    }
  ]
}
```

> `fame` 객체에 실제 적용된 검색 범위가 반환됨 (최대 2000 범위)
> 최근 90일 이내 접속한 110레벨 이상 캐릭터만 검색 가능

---

## 16. 경매장 등록 아이템 검색

`GET /df/auction`

```json
{
  "rows": [
    {
      "auctionNo": 1484323262,
      "regDate": "2026-03-08 11:21:41",
      "expireDate": "2026-03-09 11:21:41",
      "itemId": "f9941d3fa0b8253bb0b2567a29b1299f",
      "itemName": "형상화된 요기의 단서",
      "itemAvailableLevel": 1,
      "itemRarity": "유니크",
      "itemTypeId": "...",
      "itemType": "스태커블",
      "itemTypeDetailId": "...",
      "itemTypeDetail": "재료",
      "refine": 0,
      "reinforce": 0,
      "amplificationName": null,
      "fame": 0,
      "exchange": {
        "count": 1,
        "bindName": "계정귀속"
      },
      "count": 6,
      "regCount": 6,
      "price": -1,
      "currentPrice": 1980504,
      "unitPrice": 330084,
      "averagePrice": 322048
    }
  ]
}
```

---

## 17. 경매장 등록 아이템 조회

`GET /df/auction/{auctionNo}`

> 16번 검색 결과의 개별 항목과 동일한 구조 (rows 래핑 없이 단일 객체)

---

## 18. 경매장 시세 검색

`GET /df/auction-sold`

```json
{
  "rows": [
    {
      "soldDate": "2026-03-09 11:18:40",
      "itemId": "...",
      "itemName": "형상화된 요기의 단서",
      "itemAvailableLevel": 1,
      "itemRarity": "유니크",
      "itemTypeId": "...",
      "itemType": "스태커블",
      "itemTypeDetailId": "...",
      "itemTypeDetail": "재료",
      "refine": 0,
      "reinforce": 0,
      "amplificationName": null,
      "fame": 0,
      "count": 4,
      "price": 1280000,
      "unitPrice": 320000
    }
  ]
}
```

> 경매장 검색과 차이: `soldDate` 사용, `exchange`/`regCount`/`currentPrice`/`averagePrice` 없음

---

## 19. 아바타 마켓 상품 검색

`GET /df/avatar-market/sale`

```json
{
  "rows": [
    {
      "goodsNo": 4623365,
      "title": "나이트 상급2부위",
      "price": 1630000,
      "jobs": [
        { "jobId": "...", "jobName": "나이트" }
      ],
      "soldDate": null,
      "hashtag": [],
      "emblem": { "code": 100, "name": "없음" },
      "avatarSet": false,
      "avatarRarity": "상급",
      "avatarCount": 2,
      "avatar": [
        {
          "slotId": "PANTS",
          "slotName": "하의 아바타",
          "itemId": "...",
          "itemName": "...",
          "itemRarity": "커먼",
          "optionAbility": "HP MAX 280 증가",
          "emblems": []
        }
      ]
    }
  ]
}
```

---

## 20. 아바타 마켓 상품 조회

`GET /df/avatar-market/sale/{goodsNo}`

> 19번 검색 결과의 개별 항목과 동일한 구조 (rows 래핑 없이 단일 객체)

---

## 21. 아바타 마켓 상품 시세 검색

`GET /df/avatar-market/sold`

> 19번과 동일한 구조. `soldDate`에 실제 판매일이 포함됨.

---

## 22. 아바타 마켓 상품 시세 조회

`GET /df/avatar-market/sold/{goodsNo}`

> 21번 검색 결과의 개별 항목과 동일한 구조

---

## 23. 아바타 마켓 해시태그 조회

`GET /df/avatar-market/hashtag`

```json
{
  "rows": [
    "SF", "강인한", "개그", "공포", "귀여움", "깔끔한",
    "냉정한", "동물", "드라마", "만화", "몬스터", "발랄한",
    "사랑스러운", "세련된", "섹시", "시크한", "아시아",
    "악당", "악마", "영웅", "영화", "우아함", "자연",
    "전사", "전설", "제복", "중세", "천사", "청순",
    "판타지", "평범한", "흔한", "희귀한"
  ]
}
```

---

## 24. 아이템 검색

`GET /df/items`

```json
{
  "rows": [
    {
      "itemId": "f9941d3fa0b8253bb0b2567a29b1299f",
      "itemName": "형상화된 요기의 단서",
      "itemRarity": "유니크",
      "itemTypeId": "...",
      "itemType": "스태커블",
      "itemTypeDetailId": "...",
      "itemTypeDetail": "재료",
      "itemAvailableLevel": 1,
      "fame": 0
    }
  ]
}
```

> 아이템 이미지 URL: `https://img-api.neople.co.kr/df/items/{itemId}`

---

## 25. 아이템 상세 정보 조회

`GET /df/items/{itemId}`

```json
{
  "itemId": "f9941d3fa0b8253bb0b2567a29b1299f",
  "itemName": "형상화된 요기의 단서",
  "itemRarity": "유니크",
  "itemTypeId": "...",
  "itemType": "스태커블",
  "itemTypeDetailId": "...",
  "itemTypeDetail": "재료",
  "itemAvailableLevel": 1,
  "itemExplain": "요기를 추적하는 과정에서...\n<주요 사용처>\n- 요괴 섬멸 던전 입장",
  "itemExplainDetail": "...",
  "itemFlavorText": "",
  "fame": 0,
  "setItemId": null,
  "setItemName": null,
  "obtainInfo": {
    "dungeon": null,
    "shop": [
      {
        "rows": [
          { "name": "가브리엘의 비밀상점" }
        ]
      }
    ]
  }
}
```

> 장비 아이템의 경우 `status`, `growInfo`, `hashtag`, `talismanInfo` 등 추가 필드 존재

---

## 26. 아이템 상점 판매 정보 조회

`GET /df/items/{itemId}/shop`

> 인게임 백과사전 기준 상점 판매 95레벨 에픽, 100레벨 이상 유니크/레전더리/에픽 장비만 조회 가능
> 해당하지 않는 아이템은 404 반환

---

## 27. 다중 아이템 상세 정보 조회

`GET /df/multi/items?itemIds={id1},{id2}`

```json
{
  "rows": [
    {
      "itemId": "...",
      "itemName": "형상화된 요기의 단서",
      "...": "25번 아이템 상세와 동일한 필드"
    }
  ]
}
```

> 최대 15개, 중복 ID 자동 제거

---

## 28. 아이템 해시태그

`GET /df/item-hashtag`

```json
{
  "rows": [
    "불가침 무기 업그레이드", "고정 옵션", "백해 장비",
    "제작", "기계혁명", "이스핀즈", "차원회랑", "어둑섬",
    "기억 장비", "기록/흔적 장비", "아스라한", "결전 장비",
    "버프 강화", "잠식 장비"
  ]
}
```

---

## 29. 세트 아이템 검색

`GET /df/setitems`

```json
{
  "rows": [
    {
      "setItemId": "30b1fbe9358377dc71012f590b6e4dfc",
      "setItemName": "칠흑의 베르테스 전신복"
    }
  ]
}
```

---

## 30. 세트 아이템 상세 정보 조회

`GET /df/setitems/{setItemId}`

```json
{
  "setItemId": "30b1fbe9358377dc71012f590b6e4dfc",
  "setItemName": "칠흑의 베르테스 전신복",
  "setItems": [
    {
      "slotId": "JACKET",
      "slotName": "상의",
      "itemId": "...",
      "itemName": "(구)칠흑의 베르테스 상의",
      "itemRarity": "레어"
    }
  ],
  "setItemOption": [
    {
      "setEquipCount": 5,
      "explain": "암속성 피격시 2% 확률로...",
      "detailExplain": "...",
      "status": [
        { "name": "명속성저항", "value": -11 },
        { "name": "회피율", "value": "5%" }
      ],
      "reinforceSkill": [
        {
          "jobId": "...",
          "jobName": "귀검사(남)",
          "skills": [
            { "skillId": "...", "name": "대검 마스터리", "value": "2" }
          ]
        }
      ]
    }
  ]
}
```

---

## 31. 다중 세트 아이템 상세 정보 조회

`GET /df/multi/setitems?setItemIds={id1},{id2}`

> 30번과 동일한 구조가 `rows` 배열로 래핑. 최대 15개.

---

## 32. 직업 정보

`GET /df/jobs`

```json
{
  "rows": [
    {
      "jobId": "41f1cdc2ff58bb5fdc287be0db2a8df3",
      "jobName": "귀검사(남)",
      "rows": [
        {
          "jobGrowId": "df3870efe8e8754011cd12fa03cd275f",
          "jobGrowName": "웨펀마스터",
          "next": {
            "jobGrowId": "4ec01f4ae3728c080f28a72213b6df10",
            "jobGrowName": "검성",
            "next": {
              "jobGrowId": "80ec67d0356defa46a989914caca5820",
              "jobGrowName": "검신",
              "next": {
                "jobGrowId": "37495b941da3b1661bc900e68ef3b2c6",
                "jobGrowName": "眞 웨펀마스터"
              }
            }
          }
        }
      ]
    }
  ]
}
```

> 전직 체계가 `next` 중첩 구조로 표현됨 (1차 -> 2차 -> 3차 -> 眞)

---

## 33. 직업별 스킬 리스트

`GET /df/skills/{jobId}?jobGrowId={jobGrowId}`

```json
{
  "skills": [
    {
      "skillId": "7822d6d52e10964a6755f142c666b494",
      "name": "백스텝",
      "type": "active",
      "costType": "SP",
      "maxLevel": 10,
      "requiredLevel": 1,
      "requiredLevelRange": 3,
      "preRequiredSkill": null
    }
  ]
}
```

---

## 34. 직업별 스킬 상세 정보 조회

`GET /df/skills/{jobId}/{skillId}`

```json
{
  "name": "무즈 어퍼",
  "type": "active",
  "desc": "적을 높이 띄우는 어퍼컷...",
  "descDetail": "...",
  "consumeItem": null,
  "descSpecial": ["[그래플러 전직 시]\n- 독립 공격력으로 적용"],
  "maxLevel": 20,
  "requiredLevel": 1,
  "requiredLevelRange": 3,
  "preRequiredSkill": null,
  "jobId": "...",
  "jobName": "격투가(여)",
  "jobGrowLevel": [],
  "levelInfo": {
    "optionDesc": "띄우기 공격력 : {value1}%\n띄우는 힘 비율 : {value2}%\n발동 속도 증가 : {value3}%",
    "rows": [
      {
        "level": 1,
        "consumeMp": null,
        "coolTime": 2,
        "castingTime": null,
        "optionValue": {
          "value1": 191,
          "value2": 131.4,
          "value3": 10
        }
      }
    ]
  }
}
```

---

## 35. 다중 스킬 상세 정보 조회

`GET /df/multi/skills/{jobId}?skillIds={id1},{id2}`

> 34번과 동일한 구조가 `rows` 배열로 래핑. 최대 10개.

---

## 공통 참고사항

### 캐릭터 공통 필드 (03번 이후 모든 캐릭터 API)

모든 캐릭터 관련 API 응답에는 다음 공통 필드가 포함됨:

```json
{
  "serverId": "casillas",
  "characterId": "ab590098566252dad7fe024ab17f5fcc",
  "characterName": "김철완",
  "level": 115,
  "jobId": "a7a059ebe9e6054c0644b40ef316d6e9",
  "jobGrowId": "37495b941da3b1661bc900e68ef3b2c6",
  "jobName": "격투가(여)",
  "jobGrowName": "眞 넨마스터",
  "fame": 83413,
  "adventureName": "영정은날막지못해",
  "guildId": "ea891c34385b7b26712f4d5ca8927d87",
  "guildName": "SBH마스터즈"
}
```

### 이미지 URL

| 대상 | URL 패턴 |
|------|----------|
| 캐릭터 | `https://img-api.neople.co.kr/df/servers/{serverId}/characters/{characterId}?zoom={1~3}` |
| 아이템 | `https://img-api.neople.co.kr/df/items/{itemId}` |

### 에러 응답

```json
{
  "error": {
    "status": 404,
    "code": "DNF001",
    "message": "시스템 오류가 발생했습니다."
  }
}
```

### 원본 응답 파일

각 API의 전체 응답은 `docs/api_responses/` 디렉토리에 JSON 파일로 저장되어 있음.
