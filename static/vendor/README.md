# Vendored viewer — patched

`hikarin-vn-viewer.umd.js` is `hikarin-vn-viewer@1.1.6` from jsDelivr, stored
locally so the preview never depends on a CDN at request time.

## Why it is patched

The published viewer implements only four conditions:

```js
condition === "equal"        s === i
condition === "not_equal"    s !== i
condition === "greater_than" s >  i
condition === "less_than"    s <  i
```

Everything else **falls through to `false`** — silently. A script using
`"condition": "night"` always fails the test, so the branch is dead and nothing
reports a problem.

The Java engine that actually ships in Minecraft handles all ten, in
`vn/controller/vnmodules/DialogueHandler.java`:

```java
case "equal"            -> compareEquals(var, value);
case "not_equal"        -> !compareEquals(var, value);
case "less_than"        -> bothNumbers(var, value) && num(var) <  num(value);
case "greater_than"     -> bothNumbers(var, value) && num(var) >  num(value);
case "less_or_equal"    -> bothNumbers(var, value) && num(var) <= num(value);
case "greater_or_equal" -> bothNumbers(var, value) && num(var) >= num(value);
case "night"            -> !vn.isDay.get();
case "day"              -> vn.isDay.get();
case "exists"           -> var != null;
case "not_exists"       -> var == null;
```

The patch adds the six missing comparators, using the same semantics, so the
preview matches the shipped engine. Note that `night` and `day` read
`this.environment` and **ignore `var` entirely** — exactly as the SDK writes
them, with a placeholder in the variable slot.

## If you upgrade the package

Re-apply the patch, or the preview will silently fail every day/night gate
while the real mod behaves correctly. Check with:

```bash
grep -c 'condition==="night"' static/vendor/hikarin-vn-viewer.umd.js
# 1 = patched, 0 = broken
```
