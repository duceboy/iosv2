-- Inventory database (local only; contents derived from Apple binaries never go into the public repo)
CREATE TABLE IF NOT EXISTS kext(name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS kpersonality(kext TEXT, pname TEXT, ioclass TEXT, provider TEXT, match TEXT, userclient TEXT, category TEXT);
CREATE TABLE IF NOT EXISTS kclass(meta TEXT PRIMARY KEY, name TEXT, super_meta TEXT, size INTEGER, kext TEXT);
CREATE TABLE IF NOT EXISTS kvslot(class TEXT, slot INTEGER, base_name TEXT, impl TEXT);
CREATE TABLE IF NOT EXISTS kcall(kext TEXT, func TEXT, site TEXT, callee TEXT, how TEXT, argi INTEGER, sval TEXT, ival INTEGER);
CREATE TABLE IF NOT EXISTS kdispatch(kext TEXT, table_va TEXT, class TEXT, user_func TEXT, selector INTEGER, fn TEXT,
  scalar_in INTEGER, struct_in INTEGER, scalar_out INTEGER, struct_out INTEGER, entitlement TEXT, recsize INTEGER);
CREATE TABLE IF NOT EXISTS adt(path TEXT, prop TEXT, len INTEGER, sval TEXT, hex TEXT);
