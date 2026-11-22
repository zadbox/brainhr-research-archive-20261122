"""Recompute nominal and quadratic kappa from the label-only A/B export."""
from pathlib import Path
from fractions import Fraction
import json


def calculate(pairs,labels):
    pairs=[(a,b) for a,b in pairs if a!='abstain' and b!='abstain']
    lookup={v:i for i,v in enumerate(labels)}
    matrix=[[0]*len(labels) for _ in labels]
    for a,b in pairs:matrix[lookup[a]][lookup[b]]+=1
    n=len(pairs);rows=[sum(r) for r in matrix]
    columns=[sum(r[j] for r in matrix) for j in range(len(labels))]
    observed=Fraction(sum(matrix[i][i] for i in range(len(labels))),n)
    expected=Fraction(sum(a*b for a,b in zip(rows,columns)),n*n)
    result=dict(n=n,matrix=matrix,nominal_kappa=float((observed-expected)/(1-expected)))
    if labels==list(range(5)):
        distance=sum((i-j)**2*matrix[i][j] for i in range(5) for j in range(5))
        expected_distance=sum((i-j)**2*rows[i]*columns[j] for i in range(5) for j in range(5))
        result['quadratic_kappa']=float(1-Fraction(distance*n,expected_distance))
    return result


def main():
    root=Path(__file__).resolve().parents[1]
    rows=[json.loads(s) for s in (root/'annotations/AB_LABELS_ONLY.jsonl').read_text().splitlines()]
    labels=['met','partial','not_evidenced','not_met','below_threshold','contradicted']
    votes={role:[] for role in ('must_have','nice_to_have','relevance')}
    for row in rows:
        for criterion in row['criteria']:votes[criterion['role']].append((criterion['A'],criterion['B']))
        votes['relevance'].append((row['relevance']['A'],row['relevance']['B']))
    values={role:calculate(v,list(range(5)) if role=='relevance' else labels) for role,v in votes.items()}
    expected=json.loads((root/'annotations/AGREEMENT.json').read_text())['axes']
    for role,value in values.items():
        assert value['matrix']==expected[role]['matrix_rows_A_columns_B']
        assert abs(value['nominal_kappa']-expected[role]['nominal_kappa'])<1e-12
    assert abs(values['relevance']['quadratic_kappa']-expected['relevance']['quadratic_kappa'])<1e-12
    print(json.dumps(values,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
