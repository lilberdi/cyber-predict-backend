package syncjob

import "strings"

// SeedTop60 is a project allow-list of well-known CS2 orgs (not HLTV scrape).
// Used when PandaScore has no ranking endpoint on the free plan.
var SeedTop60 = []string{
	"Team Spirit", "Vitality", "MOUZ", "Falcons", "FURIA", "Natus Vincere", "NAVI", "NaVi",
	"G2", "The MongolZ", "The Mongolz", "Aurora", "Team Liquid", "FaZe", "FaZe Clan",
	"Heroic", "HEROIC", "Astralis", "Complexity", "paiN", "B8", "Legacy", "3DMAX",
	"BIG", "SAW", "Imperial", "M80", "Wildcard", "Rare Atom", "Eternal Fire",
	"Virtus.pro", "Cloud9", "MIBR", "Fluxo", "RED Canids", "Ninjas in Pyjamas",
	"OG", "fnatic", "ENCE", "BetBoom", "Passion UA", "Nemiga", "PARIVISION",
	"9z", "BESTIA", "Sharks", "FlyQuest", "Lynn Vision", "TYLOO", "GamerLegion",
	"ECSTATIC", "Metizport", "Monte", "Sangal", "Inner Circle", "Natus Vincere Junior",
	"Spirit Academy", "Liquid", "Mouz",
}

func NormalizeName(name string) string {
	s := strings.ToLower(strings.TrimSpace(name))
	switch s {
	case "navi", "navi.", "natus vincere junior":
		return "natus vincere"
	case "the mongolz", "themongolz":
		return "the mongolz"
	case "faze clan":
		return "faze"
	case "heroic":
		return "heroic"
	case "liquid":
		return "team liquid"
	case "mouz":
		return "mouz"
	default:
		return s
	}
}

func TopSet(names ...[]string) map[string]struct{} {
	out := make(map[string]struct{})
	for _, group := range names {
		for _, n := range group {
			if n == "" {
				continue
			}
			out[NormalizeName(n)] = struct{}{}
		}
	}
	return out
}

// KeepMatch reports whether the fixture is a "top teams" game.
// requireBoth: both sides must be in the set (strict top-60 derby).
func KeepMatch(team1, team2 string, top map[string]struct{}, requireBoth bool) bool {
	_, a := top[NormalizeName(team1)]
	_, b := top[NormalizeName(team2)]
	if requireBoth {
		return a && b
	}
	return a || b
}
