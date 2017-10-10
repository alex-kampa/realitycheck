import unittest
from unittest import TestCase, main
from rlp.utils import encode_hex, decode_hex
from ethereum.tools import tester as t
from ethereum.tools.tester import TransactionFailed
from ethereum.tools import keys
import time
from sha3 import keccak_256
from hashlib import sha256

import os

# Command-line flag to skip tests we're not working on
WORKING_ONLY = os.environ.get('WORKING_ONLY', False)

QINDEX_FINALIZATION_TS = 0
QINDEX_ARBITRATOR = 1
QINDEX_STEP_DELAY = 2
QINDEX_QUESTION_HASH = 3
QINDEX_BOUNTY = 4
QINDEX_ARBITRATION_BOUNTY = 5
QINDEX_BEST_ANSWER_ID = 6
QINDEX_HISTORY_HASH = 7

def calculate_commitment_hash(answer, nonce):
    return decode_hex(keccak_256(answer + decode_hex(hex(nonce)[2:].zfill(64))).hexdigest())

def calculate_commitment_id(question_id, answer_hash, bond):
    return decode_hex(keccak_256(question_id + answer_hash + decode_hex(hex(bond)[2:].zfill(64))).hexdigest())

def from_question_for_contract(txt):
    return txt

def to_answer_for_contract(txt):
    # to_answer_for_contract(("my answer")),
    return decode_hex(hex(txt)[2:].zfill(64))

def from_answer_for_contract(txt):
    return int(encode_hex(txt), 16)

class TestRealityCheck(TestCase):

    def setUp(self):

        self.c = t.Chain()

        realitycheck_code = open('RealityCheck.sol').read()
        arb_code_raw = open('Arbitrator.sol').read()
        client_code_raw = open('CallbackClient.sol').read()
        exploding_client_code_raw = open('ExplodingCallbackClient.sol').read()
        caller_backer_code_raw = open('CallerBacker.sol').read()

        # Not sure what the right way is to get pyethereum to import the dependencies
        # Pretty sure it's not this, but it does the job:
        safemath = open('SafeMath.sol').read()
        balance_holder = open('BalanceHolder.sol').read()
        realitycheck_code = realitycheck_code.replace("import './SafeMath.sol';", safemath);
        realitycheck_code = realitycheck_code.replace("import './BalanceHolder.sol';", balance_holder);

        self.rc_code = realitycheck_code
        self.arb_code = arb_code_raw
        self.client_code = client_code_raw
        self.exploding_client_code = exploding_client_code_raw
        self.caller_backer_code = caller_backer_code_raw

        self.caller_backer = self.c.contract(self.caller_backer_code, language='solidity', sender=t.k0)

        self.arb0 = self.c.contract(self.arb_code, language='solidity', sender=t.k0)
        self.c.mine()
        self.rc0 = self.c.contract(self.rc_code, language='solidity', sender=t.k0)

        self.c.mine()
        self.s = self.c.head_state

        self.question_id = self.rc0.askQuestion(
            0,
            "my question",
            self.arb0.address,
            10,
            0,
            value=1000
        )

        ts = self.s.timestamp
        self.s = self.c.head_state

        question = self.rc0.questions(self.question_id)
        self.assertEqual(int(question[QINDEX_FINALIZATION_TS]), 0)
        self.assertEqual(decode_hex(question[QINDEX_ARBITRATOR][2:]), self.arb0.address)

        self.assertEqual(question[QINDEX_STEP_DELAY], 10)
        #self.assertEqual(question[QINDEX_QUESTION_HASH], to_question_for_contract(("my question")))
        self.assertEqual(question[QINDEX_BOUNTY], 1000)

    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_fund_increase(self):

        question = self.rc0.questions(self.question_id)
        self.assertEqual(question[QINDEX_BOUNTY], 1000)

        self.rc0.fundAnswerBounty(self.question_id, value=500)
        question = self.rc0.questions(self.question_id)
        self.assertEqual(question[QINDEX_BOUNTY], 1500)

    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_no_response_finalization(self):
        # Should not be final if too soon
        self.assertFalse(self.rc0.isFinalized(self.question_id, startgas=200000))

        self.s.timestamp = self.s.timestamp + 11

        # Should not be final if there is no answer
        self.assertFalse(self.rc0.isFinalized(self.question_id, startgas=200000))

        return

    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_simple_response_finalization(self):

        gas_used = self.s.gas_used # Find out how much we used as this will affect the balance

        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(12345), 0, value=1) 
        #self.assertEqual(gas_used - self.s.gas_used, 100000)

        self.s.timestamp = self.s.timestamp + 11
        self.assertTrue(self.rc0.isFinalized(self.question_id, startgas=200000))

        self.assertEqual(from_answer_for_contract(self.rc0.getFinalAnswer(self.question_id)), 12345)



    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_earliest_finalization_ts(self):

        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(12345), 0, value=1) 
        ts1 = self.rc0.questions(self.question_id)[QINDEX_FINALIZATION_TS]

        self.s.timestamp = self.s.timestamp + 8
        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(54321), value=10) 
        ts2 = self.rc0.questions(self.question_id)[QINDEX_FINALIZATION_TS]

        self.assertTrue(ts2 > ts1, "Submitting an answer advances the finalization timestamp") 

    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_conflicting_response_finalization(self):

        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(12345), 0, value=1) 

        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(54321), 0, value=10) 

        self.s.timestamp = self.s.timestamp + 11

        self.assertTrue(self.rc0.isFinalized(self.question_id))
        self.assertEqual(from_answer_for_contract(self.rc0.getFinalAnswer(self.question_id)), 54321)

    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_arbitrator_answering_answered(self):

        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(12345), 0, value=1) 

        #self.c.mine()
        #self.s = self.c.head_state

        # The arbitrator cannot submit an answer that has not been requested. 
        # (If they really want to do this, they can always pay themselves for arbitration.)
        with self.assertRaises(TransactionFailed):
            self.arb0.submitAnswerByArbitrator(self.rc0.address, self.question_id, to_answer_for_contract(123456), keys.privtoaddr(t.k0), startgas=200000) 

        self.assertFalse(self.rc0.isFinalized(self.question_id))

        self.assertTrue(self.arb0.requestArbitration(self.rc0.address, self.question_id, value=self.arb0.getFee(), startgas=200000 ), "Requested arbitration")
        question = self.rc0.questions(self.question_id)
        self.assertEqual(question[QINDEX_FINALIZATION_TS], 1, "When arbitration is pending for an answered question, we set the finalization_ts to 1")

        # You cannot notify realitycheck of arbitration unless you are the arbitrator
        with self.assertRaises(TransactionFailed):
            self.rc0.notifyOfArbitrationRequest(self.question_id, keys.privtoaddr(t.k0), startgas=200000) 

        self.c.mine()
        self.s = self.c.head_state
        self.arb0.submitAnswerByArbitrator(self.rc0.address, self.question_id, to_answer_for_contract(123456), keys.privtoaddr(t.k0), startgas=200000) 

        self.assertTrue(self.rc0.isFinalized(self.question_id))
        self.assertEqual(from_answer_for_contract(self.rc0.getFinalAnswer(self.question_id)), 123456, "Arbitrator submitting final answer calls finalize")

    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_arbitrator_answering_unanswered(self):

        with self.assertRaises(TransactionFailed):
            self.arb0.submitAnswerByArbitrator(self.rc0.address, self.question_id, to_answer_for_contract(123456), self.arb0.address, startgas=200000) 

        self.assertFalse(self.rc0.isFinalized(self.question_id))

        self.assertTrue(self.arb0.requestArbitration(self.rc0.address, self.question_id, value=self.arb0.getFee(), startgas=200000 ), "Requested arbitration")
        question = self.rc0.questions(self.question_id)
        self.assertEqual(question[QINDEX_FINALIZATION_TS], 1, "When arbitration is pending for an answered question, we set the finalization_ts to 1")

        # You cannot submit the answer unless you are the arbitrator
        with self.assertRaises(TransactionFailed):
            self.rc0.submitAnswerByArbitrator(self.question_id, to_answer_for_contract(123456), self.arb0.address, startgas=200000) 

        self.arb0.submitAnswerByArbitrator(self.rc0.address, self.question_id, to_answer_for_contract(123456), self.arb0.address, startgas=200000) 

        self.assertTrue(self.rc0.isFinalized(self.question_id))
        self.assertEqual(from_answer_for_contract(self.rc0.getFinalAnswer(self.question_id)), 123456, "Arbitrator submitting final answer calls finalize")

    def submitAnswerReturnUpdatedState(self, st, qid, ans, max_last, bond, sdr, is_commitment = False):
        if st is None:
            st = {
                'addr': [],
                'bond': [],
                'answer': [],
                'hash': [],
                'nonce': [], # only for commitments
            }
        st['hash'].insert(0, self.rc0.questions(qid)[QINDEX_HISTORY_HASH])
        st['bond'].insert(0, bond)
        st['answer'].insert(0, to_answer_for_contract(ans))
        st['addr'].insert(0, keys.privtoaddr(sdr))
        nonce = None
        if is_commitment:
            nonce = 1234
            answer_hash = calculate_commitment_hash(to_answer_for_contract(ans), nonce)
            commitment_id = calculate_commitment_id(self.question_id, answer_hash, bond)
            self.rc0.submitAnswerCommitment(qid, answer_hash, max_last, value=bond, sender=sdr)
            st['answer'][0] = commitment_id
        else:
            self.rc0.submitAnswer(qid, to_answer_for_contract(ans), max_last, value=bond, sender=sdr)
        st['nonce'].insert(0, nonce)

        return st


    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_bond_claim_same_person_repeating_self(self):
        st = None
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 0, 2, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 2, 4, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 4, 8, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 8, 16, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 16, 32, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 32, 64, t.k3)
        self.s.timestamp = self.s.timestamp + 11
        self.rc0.claimWinnings(self.question_id, st['hash'], st['addr'], st['bond'], st['answer'], startgas=400000)
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k3)), 64+32+16+8+4+2+1000)

    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_bond_claim_same_person_contradicting_self(self):
        st = None
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 0, 2, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1002, 2, 4, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 4, 8, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1004, 8, 16, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1003, 16, 32, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 32, 64, t.k3)
        self.s.timestamp = self.s.timestamp + 11
        self.rc0.claimWinnings(self.question_id, st['hash'], st['addr'], st['bond'], st['answer'], startgas=400000)
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k3)), 64+32+16+8+4+2+1000)

    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_bond_claim_arbitration_existing_none(self):
        self.arb0.requestArbitration(self.rc0.address, self.question_id, value=self.arb0.getFee(), startgas=200000)
        st_hash = self.rc0.questions(self.question_id)[QINDEX_HISTORY_HASH]

        self.assertEqual(encode_hex(st_hash), "0"*64)

        st_addr = keys.privtoaddr(t.k4)
        st_bond = 0
        st_answer = to_answer_for_contract(1001)
        self.arb0.submitAnswerByArbitrator(self.rc0.address, self.question_id, to_answer_for_contract(1001), keys.privtoaddr(t.k4), startgas=200000) 
        hh = self.rc0.claimWinnings(self.question_id, [st_hash], [st_addr], [st_bond], [st_answer], startgas=400000)
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k4)), 1000)
        return

    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_bond_claim_arbitration_existing_final(self):
        st = None
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 0, 2, t.k4)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1002, 2, 4, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1002, 4, 8, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 8, 16, t.k4)

        self.arb0.requestArbitration(self.rc0.address, self.question_id, value=self.arb0.getFee(), startgas=200000)

        st['hash'].insert(0, self.rc0.questions(self.question_id)[QINDEX_HISTORY_HASH])
        st['addr'].insert(0, keys.privtoaddr(t.k4))
        st['bond'].insert(0, 0)
        st['answer'].insert(0, to_answer_for_contract(1001))
        self.arb0.submitAnswerByArbitrator(self.rc0.address, self.question_id, to_answer_for_contract(1001), keys.privtoaddr(t.k4), startgas=200000) 

        self.rc0.claimWinnings(self.question_id, st['hash'], st['addr'], st['bond'], st['answer'], startgas=400000)
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k4)), 16+8+4+2+1000)


    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_bond_claim_split_over_transactions(self):
        st = None
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 0, 2, t.k4)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1002, 2, 4, t.k4)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1002, 4, 8, t.k4)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 8, 16, t.k4)

        self.s.timestamp = self.s.timestamp + 11
        self.rc0.claimWinnings(self.question_id, st['hash'][:2], st['addr'][:2], st['bond'][:2], st['answer'][:2], startgas=400000)
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k4)), 16+1000)
        self.rc0.claimWinnings(self.question_id, st['hash'][2:], st['addr'][2:], st['bond'][2:], st['answer'][2:], startgas=400000)
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k4)), 16+8+4+2+1000)


    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_bond_claim_split_over_transactions_payee_later(self):
        # We can't create this state of affairs until we implement commit-reveal
        return;
        st = None
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1002,  0,  1, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001,  1,  2, t.k5)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1003,  2,  4, t.k4) # should be a commit-and-reveal for this test
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1002,  4,  8, t.k6)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001,  8, 16, t.k5)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1002, 16, 32, t.k6)

        self.arb0.requestArbitration(self.rc0.address, self.question_id, value=self.arb0.getFee(), startgas=200000)
        self.arb0.submitAnswerByArbitrator(self.rc0.address, self.question_id, to_answer_for_contract(1003), keys.privtoaddr(t.k4), startgas=200000) 

        self.s.timestamp = self.s.timestamp + 11
        self.rc0.claimWinnings(self.question_id, st['hash'][:2], st['addr'][:2], st['bond'][:2], st['answer'][:2], startgas=400000)
        self.rc0.claimWinnings(self.question_id, st['hash'][2:], st['addr'][2:], st['bond'][2:], st['answer'][2:], startgas=400000)
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k4)), 32+16+8+4+2-1+1000)
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k3)), 1+1)

    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_answer_reveal_calculation(self):
        h = calculate_commitment_hash(to_answer_for_contract(1003), 94989)
        self.assertEqual(encode_hex(h), '23e796d2bf4f5f890b1242934a636f4802aadd480b6f83c754d2bd5920f78845')

    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_answer_commit_normal(self):
        st = None
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1002,  0,  1, t.k3, True)
        nonce = st['nonce'][0]
        hh = st['hash'][0]

        with self.assertRaises(TransactionFailed):
            q = self.rc0.getFinalAnswer(self.question_id, startgas=200000)

        self.rc0.submitAnswerReveal( self.question_id, to_answer_for_contract(1002), nonce, 1, sender=t.k3, startgas=200000)

        self.s.timestamp = self.s.timestamp + 11

        q = self.rc0.getFinalAnswer(self.question_id, startgas=200000)
        self.assertEqual(from_answer_for_contract(q), 1002)

        self.rc0.claimWinnings(self.question_id, st['hash'], st['addr'], st['bond'], st['answer'], startgas=400000)
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k3)), 1001)


    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_answer_no_answer_no_commit(self):
        st = None
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1002,  0,  1, t.k3, True)
        nonce = st['nonce'][0]
        hh = st['hash'][0]

        with self.assertRaises(TransactionFailed):
            q = self.rc0.getFinalAnswer(self.question_id, startgas=200000)

        self.rc0.submitAnswerReveal( self.question_id, to_answer_for_contract(1002), nonce, 1, sender=t.k3, startgas=200000)

        self.s.timestamp = self.s.timestamp + 11

        q = self.rc0.getFinalAnswer(self.question_id, startgas=200000)
        self.assertEqual(from_answer_for_contract(q), 1002)

        self.rc0.claimWinnings(self.question_id, st['hash'], st['addr'], st['bond'], st['answer'], startgas=400000)
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k3)), 1001)



    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_answer_commit_expired(self):
        st = None
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1002,  0,  1, t.k3, True)
        nonce = st['nonce'][0]
        hh = st['hash'][0]

        self.s.timestamp = self.s.timestamp + 5
        with self.assertRaises(TransactionFailed):
            st = self.rc0.submitAnswerReveal( self.question_id, to_answer_for_contract(1002), nonce, 1, sender=t.k3)




    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_bond_claim_arbitration_existing_not_final(self):
        st = None
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 0, 2, t.k4)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1002, 2, 4, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1002, 4, 8, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 8, 16, t.k4)

        self.arb0.requestArbitration(self.rc0.address, self.question_id, value=self.arb0.getFee(), startgas=200000)

        st['hash'].insert(0, self.rc0.questions(self.question_id)[QINDEX_HISTORY_HASH])
        st['addr'].insert(0, keys.privtoaddr(t.k3))
        st['bond'].insert(0, 0)
        st['answer'].insert(0, to_answer_for_contract(1002))
        self.arb0.submitAnswerByArbitrator(self.rc0.address, self.question_id, to_answer_for_contract(1002), keys.privtoaddr(t.k3), startgas=200000) 

        self.rc0.claimWinnings(self.question_id, st['hash'], st['addr'], st['bond'], st['answer'], startgas=400000)
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k3)), 16+8+4+2+1000)


    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_min_payment_with_bond_param(self):
        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(12345), 0, value=1) 
        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(10001), 0, value=2, sender=t.k3, startgas=200000) 
        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(10002), 0, value=5, sender=t.k4, startgas=200000) 

        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(10002), 5, value=(22+5), sender=t.k5, startgas=200000) 

    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_simple_bond_claim(self):
        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(12345), 0, value=3) 

        self.s.timestamp = self.s.timestamp + 11

        self.assertEqual(from_answer_for_contract(self.rc0.getFinalAnswer(self.question_id)), 12345)

        self.rc0.claimWinnings(self.question_id, [""], [keys.privtoaddr(t.k0)], [3], [to_answer_for_contract(12345)] , startgas=400000)
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k0)), 3+1000)
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k0)), 3+1000, "Winner gets their bond back plus the bounty")

    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_bonds(self):

        claim_args_state = []
        claim_args_addrs = []
        claim_args_bonds = []
        claim_args_answs = []

        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k4)), 0)

        with self.assertRaises(TransactionFailed):
            self.rc0.submitAnswer(self.question_id, to_answer_for_contract(12345), 0, value=0, startgas=200000) 

        claim_args_state.append("")
        claim_args_addrs.append(keys.privtoaddr(t.k0))
        claim_args_bonds.append(1)
        claim_args_answs.append(to_answer_for_contract(12345))
        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(12345), 0, value=1, startgas=200000) 
        

        # "You must increase"
        with self.assertRaises(TransactionFailed):
            self.rc0.submitAnswer(self.question_id, to_answer_for_contract(10001), 0, value=1, sender=t.k3, startgas=200000) 


        claim_args_state.append(self.rc0.questions(self.question_id)[QINDEX_HISTORY_HASH])
        claim_args_addrs.append(keys.privtoaddr(t.k3))
        claim_args_bonds.append(2)
        claim_args_answs.append(to_answer_for_contract(10001))
        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(10001), 0, value=2, sender=t.k3, startgas=200000) 

        # We will ultimately finalize on this answer
        claim_args_state.append(self.rc0.questions(self.question_id)[QINDEX_HISTORY_HASH])
        claim_args_addrs.append(keys.privtoaddr(t.k4))
        claim_args_bonds.append(4)
        claim_args_answs.append(to_answer_for_contract(10002))
        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(10002), 0, value=4, sender=t.k4, startgas=200000) 

        # You have to at least double
        with self.assertRaises(TransactionFailed):
            self.rc0.submitAnswer(self.question_id, to_answer_for_contract(10003), 0, value=7, startgas=200000) 

        # You definitely can't drop back to zero
        with self.assertRaises(TransactionFailed):
            self.rc0.submitAnswer(self.question_id, to_answer_for_contract(10004), 0, value=0, startgas=200000) 

        claim_args_state.append(self.rc0.questions(self.question_id)[QINDEX_HISTORY_HASH])
        claim_args_addrs.append(keys.privtoaddr(t.k3))
        claim_args_bonds.append(11)
        claim_args_answs.append(to_answer_for_contract(10005))
        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(10005), 0, value=11, sender=t.k3, startgas=200000) 

        # The extra amount you have to send should be passed in a parameters
        #with self.assertRaises(TransactionFailed): 
        #    self.rc0.submitAnswer(self.question_id, to_answer_for_contract(10002), 0, value=(22+5), sender=t.k5, startgas=200000) 

        claim_args_state.append(self.rc0.questions(self.question_id)[QINDEX_HISTORY_HASH])
        claim_args_addrs.append(keys.privtoaddr(t.k5))
        claim_args_bonds.append(22)
        claim_args_answs.append(to_answer_for_contract(10002))
        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(10002), 11, value=22, sender=t.k5, startgas=200000) 

        ts = self.s.timestamp

        self.c.mine()
        self.s = self.c.head_state

        self.s.timestamp = ts

        self.assertFalse(self.rc0.isFinalized(self.question_id))

        #You can't claim the bond until the thing is finalized
        with self.assertRaises(TransactionFailed):
            self.rc0.claimWinnings(self.question_id, claim_args_state[::-1], claim_args_addrs[::-1], claim_args_bonds[::-1], claim_args_answs[::-1], startgas=200000)

        self.s.timestamp = self.s.timestamp + 11

        self.assertEqual(from_answer_for_contract(self.rc0.getFinalAnswer(self.question_id)), 10002)

        # First right answerer gets:
        #  - their bond back (4)
        #  - their bond again (4)
        #  - the accumulated bonds until their last answer (1 + 2)

        k4bal = 4 + 4 + 1 + 2
        self.rc0.claimWinnings(self.question_id, claim_args_state[::-1], claim_args_addrs[::-1], claim_args_bonds[::-1], claim_args_answs[::-1], startgas=400000)

        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k4)), k4bal, "First answerer gets double their bond, plus earlier bonds")

        # Final answerer gets:
        #  - their bond back (22)
        #  - the bond of the previous guy, who was wrong (11)
        #  - ...minus the payment to the lower guy (-4)
        k5bal = 22 + 11 - 4 + 1000
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k5)), k5bal, "Final answerer gets the bounty, plus their bond, plus earlier bonds up to when they took over the answer, minus the bond of the guy lower down with the right answer")

        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k3)), 0, "Wrong answerers get nothing")

        starting_bal = self.s.get_balance(keys.privtoaddr(t.k5))

        starting_gas_used = self.s.gas_used
        self.rc0.withdraw(sender=t.k5)
        gas_spent = self.s.gas_used - starting_gas_used

        ending_bal = self.s.get_balance(keys.privtoaddr(t.k5))

        self.assertEqual(ending_bal, starting_bal + k5bal - gas_spent)

        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k5)), 0)

        


    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_bond_bulk_withdrawal_other_user(self):

        st = None
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 0, 2, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 2, 4, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 4, 8, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 8, 16, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 16, 32, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 32, 64, t.k3)
        claimable = 64+32+16+8+4+2+1000

        self.s.timestamp = self.s.timestamp + 11
        self.c.mine()
        self.s = self.c.head_state

        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k3)), 0)

        # Have an unconnected user do the claim
        # This will leave the balance in the contract rather than withdrawing it
        self.rc0.claimMultipleAndWithdrawBalance([self.question_id], [len(st['hash'])], st['hash'], st['addr'], st['bond'], st['answer'], sender=t.k5, startgas=200000)
        
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k3)), claimable)


    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_bond_bulk_withdrawal_other_user(self):

        st = None
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 0, 2, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 2, 4, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 4, 8, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 8, 16, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 16, 32, t.k3)
        st = self.submitAnswerReturnUpdatedState( st, self.question_id, 1001, 32, 64, t.k3)
        claimable = 64+32+16+8+4+2+1000

        self.s.timestamp = self.s.timestamp + 11
        self.c.mine()
        self.s = self.c.head_state

        starting_bal = self.s.get_balance(keys.privtoaddr(t.k3))

        # Have the user who gets all the cash do the claim
        # This will empty their balance from the contract and assign it to their normal account
        self.rc0.claimMultipleAndWithdrawBalance([self.question_id], [len(st['hash'])], st['hash'], st['addr'], st['bond'], st['answer'], sender=t.k3, startgas=200000)
        ending_bal = self.s.get_balance(keys.privtoaddr(t.k3))
        gas_used = self.s.gas_used # Find out how much we used as this will affect the balance

        self.assertEqual(starting_bal+claimable-gas_used, ending_bal)
        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k3)), 0, "All funds are gone from the contract once withdrawal is complete")


    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_callbacks_unbundled(self):
     
        self.cb = self.c.contract(self.client_code, language='solidity', sender=t.k0)
        self.caller_backer.setRealityCheck(self.rc0.address)

        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(10005), 0, value=10, sender=t.k3, startgas=200000) 
        self.s.timestamp = self.s.timestamp + 11

        self.assertTrue(self.rc0.isFinalized(self.question_id))
        
        gas_used_before = self.s.gas_used # Find out how much we used as this will affect the balance
        self.caller_backer.fundCallbackRequest(self.question_id, self.cb.address, 3000000, value=100, startgas=200000)
        gas_used_after = self.s.gas_used # Find out how much we used as this will affect the balance

        self.assertEqual(self.caller_backer.callback_requests(self.question_id, self.cb.address, 3000000), 100)

        # Return false on an unregistered amount of gas
        with self.assertRaises(TransactionFailed):
            self.caller_backer.sendCallback(self.question_id, self.cb.address, 3000001, 0, startgas=200000)

        self.assertNotEqual(self.cb.answers(self.question_id), to_answer_for_contract(10005))
        self.caller_backer.sendCallback(self.question_id, self.cb.address, 3000000, 0)
        self.assertEqual(self.cb.answers(self.question_id), to_answer_for_contract(10005))
        
        
    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_exploding_callbacks(self):

        self.cb = self.c.contract(self.client_code, language='solidity', sender=t.k0)
        self.caller_backer.setRealityCheck(self.rc0.address)
     
        self.exploding_cb = self.c.contract(self.exploding_client_code, language='solidity', sender=t.k0)

        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(10005), 0, value=10, sender=t.k3) 
        self.s.timestamp = self.s.timestamp + 11

        self.assertTrue(self.rc0.isFinalized(self.question_id))

        self.caller_backer.fundCallbackRequest(self.question_id, self.exploding_cb.address, 3000000, value=100)
        self.assertEqual(self.caller_backer.callback_requests(self.question_id, self.exploding_cb.address, 3000000), 100)

        # return false with an unregistered or spent amount of gas
        with self.assertRaises(TransactionFailed):
            self.caller_backer.sendCallback(self.question_id, self.exploding_cb.address, 3000001, 0, startgas=200000)

        # fail if the bounty is less than we demand
        with self.assertRaises(TransactionFailed):
            self.caller_backer.sendCallback(self.question_id, self.exploding_cb.address, 3000000, 999999999999999, startgas=400000) 

        # should complete with no error, even though the client threw an error
        self.caller_backer.sendCallback(self.question_id, self.exploding_cb.address, 3000000, 0) 
    
        
    @unittest.skipIf(WORKING_ONLY, "Not under construction")
    def test_withdrawal(self):

        self.rc0.submitAnswer(self.question_id, to_answer_for_contract(12345), 0, value=100, sender=t.k5) 

        self.c.mine()
        self.s.timestamp = self.s.timestamp + 11

        self.rc0.claimWinnings(self.question_id, [""], [keys.privtoaddr(t.k5)], [100], [to_answer_for_contract(12345)], sender=t.k5, startgas=200000)

        starting_deposited = self.rc0.balanceOf(keys.privtoaddr(t.k5))
        self.assertEqual(starting_deposited, 1100)

        # Mine to reset the gas used to 0
        self.c.mine()
        self.s = self.c.head_state

        self.assertEqual(self.s.gas_used, 0)

        starting_bal = self.s.get_balance(keys.privtoaddr(t.k5))
        self.rc0.withdraw(sender=t.k5, startgas=100000)
        ending_bal = self.s.get_balance(keys.privtoaddr(t.k5))

        gas_used = self.s.gas_used # Find out how much we used as this will affect the balance

        self.assertEqual(self.rc0.balanceOf(keys.privtoaddr(t.k5)), 0)
        self.assertEqual(ending_bal, starting_bal + starting_deposited - gas_used)

        return


if __name__ == '__main__':
    main()
