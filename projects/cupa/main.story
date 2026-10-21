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
      "scope": "WORLD",
      "var": "affection",
      "condition": "less_than",
      "value": "10",
      "_target": "warm_check"
    }
  },
  {
    "kind": "say",
    "data": {
      "label": "Cupa",
      "content": "Oh. It's you. What do you want."
    }
  },
  {
    "kind": "end",
    "data": {}
  },
  {
    "kind": "label",
    "data": {
      "name": "warm_check"
    }
  },
  {
    "kind": "if",
    "data": {
      "scope": "",
      "var": "isNight",
      "condition": "equal",
      "value": "true",
      "_target": "morning"
    }
  },
  {
    "kind": "say",
    "data": {
      "label": "Cupa",
      "content": "Can't sleep either? Stay with me a while."
    }
  },
  {
    "kind": "end",
    "data": {}
  },
  {
    "kind": "label",
    "data": {
      "name": "morning"
    }
  },
  {
    "kind": "say",
    "data": {
      "label": "Cupa",
      "content": "Good morning, Master. You slept well?"
    }
  },
  {
    "kind": "end",
    "data": {}
  }
]
