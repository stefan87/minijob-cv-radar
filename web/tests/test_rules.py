import unittest
from collector import analyse,schedule_evidence,hits,distance
class Rules(unittest.TestCase):
    def setUp(self):
        self.c={'mode':'cv','centre':[48.137154,11.576124],'radius_km':15,'skills':['Jira','support'],'delivery_terms':['fahrer','kurier']}
        self.d={'titel':'Minijob Support','arbeitszeitmodelle':['MINIJOB'],'stellenbeschreibung':'Jira support','arbeitsorte':[{'ort':'Munich','koordinaten':{'lat':48.137154,'lon':11.576124}}]}
    def test_local(self):self.assertIsNotNone(analyse({'refnr':'1'},self.d,self.c,'local'))
    def test_not_fulltime(self):
        self.d['titel']='Support';self.d['arbeitszeitmodelle']=['VOLLZEIT'];self.assertIsNone(analyse({},self.d,self.c,'local'))
    def test_remote_not_hybrid(self):
        self.d['arbeitsorte']=[{'land':'Deutschland'}];self.d['stellenbeschreibung']='Jira support Homeoffice moeglich';self.assertIsNone(analyse({},self.d,self.c,'national'))
        self.d['stellenbeschreibung']='Jira support 100% remote';self.assertIsNotNone(analyse({},self.d,self.c,'national'))
    def test_negated_remote(self):
        self.d['arbeitsorte']=[];self.d['stellenbeschreibung']='Jira nicht 100% remote';self.assertIsNone(analyse({},self.d,self.c,'national'))
    def test_schedule(self):
        self.assertFalse(schedule_evidence('Flexible Arbeitszeiten und Schichtarbeit'))
        self.assertTrue(schedule_evidence('Arbeitszeit ab 17 Uhr'))
        self.assertFalse(schedule_evidence('Arbeitszeit ab 16 Uhr'))
    def test_delivery_no_cv(self):
        self.c['mode']='delivery';self.d['titel']='Minijob Fahrer';self.d['stellenbeschreibung']='Arbeitszeit ab 18 Uhr';j=analyse({},self.d,self.c,'local');self.assertIsNotNone(j);self.assertEqual(j['matched_skills'],[])
    def test_distance(self):self.assertEqual(distance([48,11],[48,11]),0)
if __name__=='__main__':unittest.main()
