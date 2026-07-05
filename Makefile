# Run from the collection root (not from extensions/): that is what lets
# molecule auto-discover extensions/molecule/config.yml and engage the
# pinned dependency step.
export MOLECULE_GLOB := extensions/molecule/*/molecule.yml

.PHONY: test
test:
	molecule test --all

.PHONY: converge
converge:
	molecule converge --all

.PHONY: destroy
destroy:
	molecule destroy --all
