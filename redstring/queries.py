"""The Cypher that carries the product. Each one is wrapped as a named tool in tools.py,
so agents never write raw Cypher.

These follow the spec's P1 and Q0-Q5, with a few changes found while running them on the seed;
each change is marked CHANGE and listed in the README.
"""

# ---------------------------------------------------------------- agency graph

# P1. Fingerprint projection. Producer, after writing a Draft in the client graph.
# CHANGE: kind is a parameter (post, draft, spec) and `active` lets a revision retire
# the fingerprint it replaces, so a blocked draft stops counting against anyone.
P1_PROJECT_FINGERPRINT = """
MERGE (f:Fingerprint {id: $draft_id})
SET f.kind = $kind, f.business_id = $client, f.created_at = $now, f.active = true
WITH f
MATCH (b:Business {id: $client})
MERGE (f)-[:OF]->(b)
WITH f
UNWIND $technique_ids AS tid
MATCH (t:Technique {id: tid})
MERGE (f)-[:USES]->(t)
"""

RETIRE_FINGERPRINT = """
MATCH (f:Fingerprint {id: $id}) SET f.active = false, f.retired_at = $now
"""

# Q0. Derive signatures. After seeding and after each new post.
# CHANGE: clears stale SIGNATURE edges first, and only active fingerprints count.
Q0_CLEAR_SIGNATURES = "MATCH ()-[s:SIGNATURE]->() DELETE s"
Q0_DERIVE_SIGNATURES = """
MATCH (b:Business)<-[:OF]-(f:Fingerprint)
WHERE f.active
WITH b, count(f) AS total
MATCH (b)<-[:OF]-(f:Fingerprint)-[:USES]->(t:Technique)
WHERE f.active AND t.rarity >= $rare
WITH b, t, total, count(f) AS uses
WHERE toFloat(uses) / total >= $share
MERGE (b)-[s:SIGNATURE]->(t)
SET s.share = toFloat(uses) / total
RETURN b.name AS business, t.name AS technique, t.id AS technique_id, s.share AS share
ORDER BY business, share DESC
"""

# Q1. Lead conflict check. Scout. Second half is the multi-hop path:
# lead -> audience -> overlapping audience -> client. The app sums conflict per client.
# OVERLAPS is stored once per pair and matched undirected.
Q1_LEAD_CONFLICT = """
MATCH (lead:Business {id: $lead})-[tl:TARGETS]->(a:Audience)<-[tc:TARGETS]-(c:Business {status: 'signed'})
RETURN c.id AS client_id, c.name AS client, c.category = lead.category AS same_category,
       a.name AS via, null AS hop, tl.weight * tc.weight AS conflict
UNION ALL
MATCH (lead:Business {id: $lead})-[tl:TARGETS]->(la:Audience)-[o:OVERLAPS]-(a:Audience)<-[tc:TARGETS]-(c:Business {status: 'signed'})
RETURN c.id AS client_id, c.name AS client, c.category = lead.category AS same_category,
       a.name AS via, la.name AS hop, tl.weight * tc.weight * o.share AS conflict
"""

# Same category in the same neighborhood is an automatic decline.
Q1_SAME_AREA_COMPETITOR = """
MATCH (lead:Business {id: $lead})-[:LOCATED_IN]->(n:Neighborhood)<-[:LOCATED_IN]-(c:Business {status: 'signed'})
WHERE c.category = lead.category
RETURN c.id AS client_id, c.name AS client, n.name AS neighborhood
"""

# Audience overlap between two businesses, same paths as Q1. Q2 risk = similarity x this (clamped to 1).
AUDIENCE_OVERLAP = """
MATCH (x:Business {id: $a})-[tx:TARGETS]->(au:Audience)<-[ty:TARGETS]-(y:Business {id: $b})
RETURN tx.weight * ty.weight AS conflict
UNION ALL
MATCH (x:Business {id: $a})-[tx:TARGETS]->(:Audience)-[o:OVERLAPS]-(au:Audience)<-[ty:TARGETS]-(y:Business {id: $b})
RETURN tx.weight * ty.weight * o.share AS conflict
"""

# Q2. Double Take. Standards. Similarity counts only rare techniques, weighted by rarity, against
# any active fingerprint from a business that shares an audience and is signed or an open pursuit.
# CHANGE: only active fingerprints count; passed prospects count until their cooldown ends.
Q2_DOUBLE_TAKE = """
MATCH (d:Fingerprint {id: $draft})-[:OF]->(me:Business)-[:TARGETS]->(:Audience)<-[:TARGETS]-(other:Business)
WHERE other <> me AND (other.status IN ['signed', 'pursued', 'pitched']
      OR (other.status = 'passed' AND other.passed_at >= $cooldown_cutoff))
WITH DISTINCT d, other
MATCH (d)-[:USES]->(t:Technique)<-[:USES]-(of:Fingerprint)-[:OF]->(other)
WHERE t.rarity >= $rare AND of.active
WITH d, other, collect(DISTINCT t) AS shared
MATCH (d)-[:USES]->(mine:Technique)
WITH other, shared, sum(mine.rarity) AS total
RETURN other.id AS business_id, other.name AS business, other.status AS status,
       [t IN shared | t.id] AS shared_ids, [t IN shared | t.name] AS shared_rare,
       reduce(s = 0.0, t IN shared | s + t.rarity) / total AS similarity
ORDER BY similarity DESC
"""

# Which of `other`'s fingerprints carry the shared techniques: evidence for the CollisionFlag.
Q2_EVIDENCE = """
MATCH (f:Fingerprint)-[:OF]->(:Business {id: $other})
WHERE f.active
MATCH (f)-[:USES]->(t:Technique)
WHERE t.id IN $shared
WITH f, collect(t.id) AS hits
RETURN f.id AS fingerprint, f.kind AS kind, size(hits) AS hits
ORDER BY hits DESC LIMIT 5
"""

# Q3. Open territory. Style Director. Techniques in a style that no overlapping business has
# claimed as a signature, rarest first.
# CHANGE: open pursuits count as claimants too (so two pitches do not converge), $avoid excludes
# the techniques a CollisionFlag named, and techniques need at least one reference as evidence.
Q3_OPEN_TERRITORY = """
MATCH (me:Business {id: $client})
OPTIONAL MATCH (me)-[:TARGETS]->(:Audience)<-[:TARGETS]-(other:Business)
WHERE other <> me AND other.status IN ['signed', 'pursued', 'pitched']
OPTIONAL MATCH (other)-[:SIGNATURE]->(claimed:Technique)
WITH collect(DISTINCT claimed.id) AS taken
MATCH (t:Technique)-[:PART_OF]->(:Style {name: $style})
WHERE NOT t.id IN taken AND NOT t.id IN $avoid
OPTIONAL MATCH (t)<-[:USES]-(r:Reference)
WITH t, count(r) AS examples
WHERE examples > 0
RETURN t.id AS technique_id, t.name AS technique, t.category AS category, t.rarity AS rarity, examples
ORDER BY rarity DESC, examples DESC
LIMIT 12
"""

# References that show a technique, best evidence first. Producer uses these for INSPIRED_BY.
REFERENCES_FOR = """
MATCH (r:Reference)-[:USES]->(t:Technique)
WHERE t.id IN $techniques
  AND NOT r.id IN $exclude
  AND NOT r.creator IN $exclude_creators
WITH r, count(DISTINCT t) AS hits, r.category = $category AS same
RETURN r.id AS id, r.url AS url, r.creator AS creator, r.category AS category, hits, same
ORDER BY hits + CASE WHEN same THEN 1 ELSE 0 END DESC, same DESC, hits DESC, r.id
LIMIT $fetch
"""

STYLES = """
MATCH (s:Style)<-[:PART_OF]-(t:Technique)
RETURN s.id AS id, s.name AS name, count(t) AS techniques, avg(t.rarity) AS avg_rarity
ORDER BY name
"""

PIPELINE = """
MATCH (b:Business)
OPTIONAL MATCH (a:Agent)-[:OWNS]->(b)
OPTIONAL MATCH (:Agent)-[s:SCREENED]->(b)
RETURN b.id AS id, b.name AS name, b.category AS category, b.status AS status,
       a.name AS owner, s.verdict AS verdict, s.reason AS reason
ORDER BY name
"""

# ---------------------------------------------------------------- client graph

# Q4. Decision trace. Feeds the route card.
# CHANGE: sources also label Drafts (by hook), Audits (by summary) and CollisionFlags (by business).
Q4_DECISION_TRACE = """
MATCH (d:Draft {id: $draft})
OPTIONAL MATCH (d)<-[:INCLUDES]-(:Plan)-[:SERVES]->(g:Goal)
OPTIONAL MATCH (dec:Decision)-[:AFFECTS]->(d)
OPTIONAL MATCH (dec)-[:DECIDED_BY]->(a:Agent)
OPTIONAL MATCH (dec)-[:BASED_ON]->(src)
OPTIONAL MATCH (d)-[:INSPIRED_BY]->(r:Reference)
RETURN d.hook AS draft, d.status AS status, g.text AS goal, g.status AS goal_status,
       collect(DISTINCT {decision: dec.text, by: a.name, at: dec.at, rationale: dec.rationale}) AS decisions,
       collect(DISTINCT {kind: labels(src)[0], text: coalesce(src.text, src.url, src.summary, src.hook, src.with_business), source_url: src.source_url}) AS sources,
       d.spec AS spec,
       collect(DISTINCT {url: r.url, creator: r.creator, category: r.category}) AS references
"""

# Lineage and flags, shown under the route card.
DRAFT_LINEAGE = """
MATCH (d:Draft {id: $draft})
OPTIONAL MATCH p = (d)-[:REVISION_OF*1..5]->(prev:Draft)
OPTIONAL MATCH (cf:CollisionFlag)-[:FLAGS]->(prev)
OPTIONAL MATCH (d)-[:USES]->(t:Technique)
RETURN collect(DISTINCT {id: prev.id, hook: prev.hook, version: prev.version}) AS previous,
       collect(DISTINCT {with: cf.with_business, shared: cf.shared_techniques, similarity: cf.similarity, risk: cf.risk}) AS flags,
       collect(DISTINCT t.name) AS techniques
"""

# Q5. Stale drafts after a goal changes.
Q5_STALE_DRAFTS = """
MATCH (g:Goal {status: 'retired'})<-[:SERVES]-(:Plan)-[:INCLUDES]->(d:Draft)
WHERE d.status IN ['queued', 'approved']
RETURN d.id AS draft, d.hook AS hook, g.text AS retired_goal
"""

# Pitch route card: every claim the pitch makes, with its source.
PITCH_TRACE = """
MATCH (p:Pitch {id: $pitch})
OPTIONAL MATCH (p)-[:SERVES]->(g:Goal)
OPTIONAL MATCH (p)-[:CITES]->(f:Finding)
OPTIONAL MATCH (p)-[:SHOWS]->(d:Draft)
OPTIONAL MATCH (dec:Decision)-[:AFFECTS]->(p)
OPTIONAL MATCH (dec)-[:DECIDED_BY]->(a:Agent)
RETURN p.id AS pitch, p.angle AS angle, p.status AS status,
       g.text AS goal, g.status AS goal_status,
       collect(DISTINCT {id: f.id, kind: f.kind, text: f.text, source_url: f.source_url}) AS claims,
       collect(DISTINCT {id: d.id, hook: d.hook, status: d.status}) AS spec_posts,
       collect(DISTINCT {decision: dec.text, by: a.name, at: dec.at}) AS decisions
"""
