package syncjob

import "testing"

func TestKeepMatchBothRequired(t *testing.T) {
	top := TopSet(SeedTop60)
	if !KeepMatch("Team Spirit", "Vitality", top, true) {
		t.Fatal("expected Spirit vs Vitality kept")
	}
	if KeepMatch("Team Spirit", "Random Academy", top, true) {
		t.Fatal("strict mode should drop unknown opponent")
	}
	if !KeepMatch("Team Spirit", "Random Academy", top, false) {
		t.Fatal("relaxed mode should keep one top team")
	}
}
