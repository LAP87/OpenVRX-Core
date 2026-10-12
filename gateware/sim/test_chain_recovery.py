"""Real run_seed stimulus routing up to the simulation boundary; no HDL acceptance."""
import hashlib
from pathlib import Path

import pytest
import test_fuzz_chain as chain

GOLD = {1345: {'a': 'f43cc70cab8ace213c194219db49d120a42aad46f528cd16943086b367e6289b', 'b': 'f81cf17c391bfdcfbe712fedf90e9f9c7a890cb20e72dd33d685e0b139004af3'}, 1400: {'a': '2c4b2169089c68a753d1c3b302b077fb106717d3a8b21670e87ec9470527e120', 'b': '2aaf325ec6a50914b154a97ab806a511b5529de3fd51f3cde74c8cad660fbc3a'}, 1601: {'a': '792c237af3e4f42154ee09131d742d7132c95d813f8d70497723498d8246e36b', 'b': '533048a277ec8c422f57cdc6765430135d6bc676454ca1dc223558bb811fca22'}}

class StopAtSimulation(RuntimeError):
    pass


@pytest.mark.parametrize('seed,geometry,density,fields,force', [
    (1345,'scaled',2.5,10,()), (1400,'scaled',1.0,10,('b_edge',)),
    (1601,'full',1.0,8,('pal','mode_switch'))])
@pytest.mark.parametrize('recovery', [0,4])
def test_real_seed_entry_keeps_original_or_native_golden(monkeypatch, tmp_path, seed, geometry, density, fields, force, recovery):
    original = chain.fz.generate(seed, n_fields=fields, force=force, geometry=geometry, density=density)
    seen = {}
    def stop(scenario,*args,**kwargs):
        seen['scenario'] = scenario
        raise StopAtSimulation()
    monkeypatch.setattr(chain,'run_sim',stop)
    with pytest.raises(StopAtSimulation):
        chain.run_seed(seed,work=tmp_path,n_fields=fields,force=force,geometry=geometry,density=density,recovery_fields=recovery)
    scenario=seen['scenario']
    assert scenario.ctl==original.ctl
    for channel,data,prefix in [('a',scenario.a,original.a),('b',scenario.b,original.b)]:
        assert data.startswith(prefix)
        if recovery:
            wire=''.join(f'{byte:02x}\n' for byte in data).encode()
            assert hashlib.sha256(wire).hexdigest()==GOLD[seed][channel]
        else:
            assert data==prefix
    assert len(scenario.camera)==len(original.camera)+recovery


@pytest.mark.parametrize('count', [-1,True,False,None,1.5])
def test_seed_rejects_invalid_recovery_before_generation(monkeypatch, count):
    def forbidden(*a,**kw):
        pytest.fail('invalid recovery reached generator')
    monkeypatch.setattr(chain.fz,'generate',forbidden)
    with pytest.raises(ValueError,match='nonnegative integer'):
        chain.run_seed(1,recovery_fields=count)
