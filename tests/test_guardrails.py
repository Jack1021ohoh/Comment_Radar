from agent.guardrails import accusations, scrub


def test_flags_single_account_labels():
    assert accusations("acct_1a2b3c is a bot that posts every hour")
    assert accusations("We think acct_1a2b3c, which joined in May, is clearly fake.")
    assert accusations("acct_00ff00 looks like a paid shill")


def test_group_language_passes():
    assert not accusations("The 6 accounts in this group posted near-identical praise within 12 minutes.")
    assert not accusations("acct_1a2b3c was created 20 days before commenting.")
    assert not accusations("This group is likely a promotion ring for an investment scam.")


def test_scrub_removes_the_label():
    out = scrub("Notably acct_1a2b3c is a bot.")
    assert "bot" not in out and "acct_1a2b3c" not in out
