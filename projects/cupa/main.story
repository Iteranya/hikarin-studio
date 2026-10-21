[
  {
    "kind": "label",
    "data": {
      "name": "start"
    }
  },
  {
    "kind": "if",
    "data": {
      "scope": "MAID",
      "var": "seen.night_01",
      "condition": "equal",
      "value": "false",
      "_target": "night_01"
    }
  },
  {
    "kind": "if",
    "data": {
      "scope": "PLAYER",
      "var": "advancement.minecraft:nether",
      "condition": "equal",
      "value": "true",
      "_target": "nether_chat"
    }
  },
  {
    "kind": "say",
    "data": {
      "label": "Cupa",
      "content": "Oh! You're back."
    }
  },
  {
    "kind": "idle",
    "data": {}
  },
  {
    "kind": "end",
    "data": {}
  },
  {
    "kind": "label",
    "data": {
      "name": "nether_chat"
    }
  },
  {
    "kind": "say",
    "data": {
      "label": "Cupa",
      "content": "You went to the Nether without me?"
    }
  },
  {
    "kind": "end",
    "data": {}
  }
]
