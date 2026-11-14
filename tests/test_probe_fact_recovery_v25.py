import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from recover_probe_facts_v25 import anchored_facts

class AnchoredFactTests(unittest.TestCase):
    def test_quotes_are_literal_source_not_model_paraphrases(self):
        source='Alice founded the group.\nMembership reached 42.'
        data={'facts':[{'type':'entity','question':'Who founded the group?','answer':'Alice','line_id':0,'quote':'invented'},
                       {'type':'number','question':'How many members?','answer':'42','line_id':1,'quote':'invented'}]}
        result=anchored_facts(data,source,['entity','number'])
        self.assertEqual(len(result),2)
        self.assertTrue(all(x['quote']in source and x['answer']in x['quote']for x in result))
    def test_unsupported_answer_and_invalid_line_are_rejected(self):
        for line,answer in [(0,'Bob'),(True,'Alice'),(10,'Alice')]:
            data={'facts':[{'type':'entity','question':'Who founded it?','answer':answer,'line_id':line}]}
            self.assertEqual(anchored_facts(data,'Alice founded it.',['entity','number']),[])
