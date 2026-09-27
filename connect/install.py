# Copyright (c) 2026
# For license information, please see license.txt

from connect.patches import seed_starter_packs


def after_install():
	# A fresh install marks every patch as already run without running it, so
	# seed data that lives in a patch has to be loaded here as well.
	seed_starter_packs.execute()
