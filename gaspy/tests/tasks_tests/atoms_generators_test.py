''' Tests for the `gaspy.tasks.generators` submodule '''

__author__ = 'Kevin Tran'
__email__ = 'ktran@andrew.cmu.edu'

# Modify the python path so that we find/use the .gaspyrc.json in the testing
# folder instead of the main folder
import os
os.environ['PYTHONPATH'] = '/home/GASpy/gaspy/tests:' + os.environ['PYTHONPATH']

# Things we're testing
from ...tasks.atoms_generators import (GenerateGas,
                                       GenerateBulk,
                                       GenerateSlabs,
                                       _make_slab_docs_from_structs,
                                       GenerateAdsorptionSites,
                                       GenerateAdslabs)

# Things we need to do the tests
import os
import pytest
import pickle
import numpy.testing as npt
import ase.io
from ase.collections import g2
from pymatgen.ext.matproj import MPRester
from pymatgen.io.ase import AseAtomsAdaptor
from .utils import clean_up_task
from ... import defaults
from ...atoms_operators import make_slabs_from_bulk_atoms
from ...tasks import get_task_output, evaluate_luigi_task
from ...utils import read_rc, unfreeze_dict
from ...mongo import make_atoms_from_doc

TEST_CASE_LOCATION = '/home/GASpy/gaspy/tests/test_cases/'
REGRESSION_BASELINES_LOCATION = ('/home/GASpy/gaspy/tests/regression_baselines'
                                 '/tasks/atoms_generators/')


@pytest.mark.parametrize('gas_name', ['CO', 'H'])
def test_GenerateGas(gas_name):
    task = GenerateGas(gas_name)

    try:
        # Create, fetch, and parse the output of the task
        evaluate_luigi_task(task)
        doc = get_task_output(task)
        atoms = make_atoms_from_doc(doc)

        # Verify that the task worked by comparing it with what should be made
        expected_atoms = g2[gas_name]
        expected_atoms.positions += 10.
        expected_atoms.cell = [20, 20, 20]
        expected_atoms.pbc = [True, True, True]
        assert atoms == expected_atoms

    # Clean up
    finally:
        clean_up_task(task)


@pytest.mark.parametrize('mpid', ['mp-30', 'mp-867306'])
def test_GenerateBulk(mpid):
    task = GenerateBulk(mpid)

    try:
        # Create, fetch, and parse the output of the task
        evaluate_luigi_task(task)
        doc = get_task_output(task)
        atoms = make_atoms_from_doc(doc)

        # Verify that the task worked by comparing it with Materials Project
        with MPRester(read_rc('matproj_api_key')) as rester:
            structure = rester.get_structure_by_material_id(mpid)
        expected_atoms = AseAtomsAdaptor.get_atoms(structure)
        assert atoms == expected_atoms

    # Clean up
    finally:
        clean_up_task(task)


def test_GenerateSlabs():
    '''
    There are a lot of moving parts in here, so we rely on the unit testing of
    the underlying functions to ensure fidelity of this task. This test will
    instead verify that the output types of this task are what we expected them
    to be.
    '''
    mpid = 'mp-2'
    miller_indices = (1, 0, 0)
    slab_generator_settings = defaults.SLAB_SETTINGS['slab_generator_settings']
    get_slab_settings = defaults.SLAB_SETTINGS['get_slab_settings']
    bulk_vasp_settings = defaults.BULK_SETTINGS['vasp']

    # Make the task and make sure the arguments were parsed correctly
    task = GenerateSlabs(mpid=mpid,
                         miller_indices=miller_indices,
                         slab_generator_settings=slab_generator_settings,
                         get_slab_settings=get_slab_settings,
                         bulk_vasp_settings=bulk_vasp_settings)
    assert task.mpid == mpid
    assert task.miller_indices == miller_indices
    assert unfreeze_dict(task.slab_generator_settings) == slab_generator_settings
    assert unfreeze_dict(task.get_slab_settings) == get_slab_settings
    assert unfreeze_dict(task.bulk_vasp_settings) == bulk_vasp_settings

    try:
        # Run the task and make sure the task output has the correct format/fields
        evaluate_luigi_task(task)
        docs = get_task_output(task)
        for doc in docs:
            assert isinstance(doc['shift'], float)
            assert isinstance(doc['top'], bool)
            _ = make_atoms_from_doc(doc)    # noqa: F841

    finally:
        clean_up_task(task)


@pytest.mark.baseline
def test_to_create_slab_docs_from_structs():
    '''
    Apply this function to all our slabs at once and save the results.
    '''
    # Make the documents for each bulk test case
    bulks_folder = TEST_CASE_LOCATION + 'bulks/'
    for file_name in os.listdir(bulks_folder):
        bulk = ase.io.read(bulks_folder + file_name)
        structs = make_slabs_from_bulk_atoms(bulk, (1, 1, 1,),
                                             defaults.SLAB_SETTINGS['slab_generator_settings'],
                                             defaults.SLAB_SETTINGS['get_slab_settings'])
        docs = _make_slab_docs_from_structs(structs)

        # Save them
        bulk_name = file_name.split('.')[0]
        with open(REGRESSION_BASELINES_LOCATION + 'slab_docs_%s.pkl' % bulk_name, 'wb') as file_handle:
            pickle.dump(docs, file_handle)
    assert True


def test__make_slab_docs_from_structs():
    '''
    Another regression test because we rely mainly on the unit tests of the
    functions that `_make_slab_docs_from_structs` relies on.
    '''
    # Make the documents for each test case
    bulks_folder = TEST_CASE_LOCATION + 'bulks/'
    for file_name in os.listdir(bulks_folder):
        bulk = ase.io.read(bulks_folder + file_name)
        structs = make_slabs_from_bulk_atoms(bulk, (1, 1, 1,),
                                             defaults.SLAB_SETTINGS['slab_generator_settings'],
                                             defaults.SLAB_SETTINGS['get_slab_settings'])
        docs = _make_slab_docs_from_structs(structs)


    # Get the regression baseline
    bulk_name = file_name.split('.')[0]
    with open(REGRESSION_BASELINES_LOCATION + 'slab_docs_%s.pkl' % bulk_name, 'rb') as file_handle:
        expected_docs = pickle.load(file_handle)

    # Remove creation and modification times because we don't care about
    # those... and they will be wrong
    for doc in docs + expected_docs:
        doc.pop('ctime', None)
        doc.pop('mtime', None)
    assert docs == expected_docs


def test_GenerateAdsorptionSites():
    '''
    WARNING:  This test uses `evaluate_luigi_task`, which has a chance of
    actually submitting a FireWork to production. To avoid this, you must try
    to make an Adslab from a bulk that shows up in the unit_testing_atoms Mongo
    collection. If you copy/paste this test into somewhere else, make sure
    that you use `evaluate_luigi_task` appropriately.
    '''
    mpid = 'mp-2'
    miller_indices = (1, 0, 0)
    min_xy = defaults.ADSLAB_SETTINGS['min_xy']
    slab_generator_settings = defaults.SLAB_SETTINGS['slab_generator_settings']
    get_slab_settings = defaults.SLAB_SETTINGS['get_slab_settings']
    bulk_vasp_settings = defaults.BULK_SETTINGS['vasp']

    # Make the task and make sure the arguments were parsed correctly
    task = GenerateAdsorptionSites(mpid=mpid,
                                   miller_indices=miller_indices,
                                   min_xy=min_xy,
                                   slab_generator_settings=slab_generator_settings,
                                   get_slab_settings=get_slab_settings,
                                   bulk_vasp_settings=bulk_vasp_settings)
    assert task.mpid == mpid
    assert task.miller_indices == miller_indices
    assert task.min_xy == min_xy
    assert unfreeze_dict(task.slab_generator_settings) == slab_generator_settings
    assert unfreeze_dict(task.get_slab_settings) == get_slab_settings
    assert unfreeze_dict(task.bulk_vasp_settings) == bulk_vasp_settings

    try:
        evaluate_luigi_task(task)
        docs = get_task_output(task)

        for doc in docs:
            assert isinstance(doc['shift'], float)
            assert isinstance(doc['top'], bool)
            assert isinstance(doc['slab_repeat'], tuple)

            atoms = make_atoms_from_doc(doc)
            for atom in atoms:
                if atom.tag == 1:
                    npt.assert_allclose(atom.position, doc['adsorption_site'])
                    assert atom.symbol == 'U'

    finally:
        clean_up_task(task)


def test_GenerateAdslabs():
    '''
    WARNING:  This test uses `evaluate_luigi_task`, which has a chance of
    actually submitting a FireWork to production. To avoid this, you must try
    to make an Adslab from a bulk that shows up in the unit_testing_atoms Mongo
    collection. If you copy/paste this test into somewhere else, make sure
    that you use `evaluate_luigi_task` appropriately.

    We only test some superficial things here. We rely heavily on the test for
    the `add_adsorbate_onto_slab` function to make sure things go right.
    '''
    adsorbate_name = 'OH'
    rotation = defaults.ADSLAB_SETTINGS['rotation']
    mpid = 'mp-2'
    miller_indices = (1, 0, 0)
    min_xy = defaults.ADSLAB_SETTINGS['min_xy']
    slab_generator_settings = defaults.SLAB_SETTINGS['slab_generator_settings']
    get_slab_settings = defaults.SLAB_SETTINGS['get_slab_settings']
    bulk_vasp_settings = defaults.BULK_SETTINGS['vasp']

    # Make the task and make sure the arguments were parsed correctly
    task = GenerateAdslabs(adsorbate_name=adsorbate_name,
                           rotation=rotation,
                           mpid=mpid,
                           miller_indices=miller_indices,
                           min_xy=min_xy,
                           slab_generator_settings=slab_generator_settings,
                           get_slab_settings=get_slab_settings,
                           bulk_vasp_settings=bulk_vasp_settings)
    assert task.adsorbate_name == adsorbate_name
    assert unfreeze_dict(task.rotation) == rotation
    assert task.mpid == mpid
    assert task.miller_indices == miller_indices
    assert task.min_xy == min_xy
    assert unfreeze_dict(task.slab_generator_settings) == slab_generator_settings
    assert unfreeze_dict(task.get_slab_settings) == get_slab_settings
    assert unfreeze_dict(task.bulk_vasp_settings) == bulk_vasp_settings

    try:
        # Run the task and fetch the outputs
        evaluate_luigi_task(task)
        docs = get_task_output(task)
        for doc in docs:
            adslab = make_atoms_from_doc(doc)

            # Make sure the extra document fields are correct
            npt.assert_allclose(adslab[0].position, doc['adsorption_site'])
            assert isinstance(doc['shift'], float)
            assert isinstance(doc['top'], bool)
            assert isinstance(doc['slab_repeat'], tuple)

            # Make sure that the adsorbate was rotated correctly by checking
            # the positions of the adsorbate
            adsorbate = defaults.ADSORBATES[adsorbate_name].copy()
            adsorbate.euler_rotate(**rotation)
            npt.assert_allclose(adslab[0:len(adsorbate)].get_positions() - doc['adsorption_site'],
                                adsorbate.positions)

    finally:
        clean_up_task(task)
