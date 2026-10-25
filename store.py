import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
if not REGION:
    raise RuntimeError("Definis la region : export AWS_REGION=eu-west-3")

TABLE_LIENS = "liens"
dynamo = boto3.client(
    "dynamodb", region_name=REGION, config=Config(max_pool_connections=50)
)


def creer_lien(lien_id, restants):
    dynamo.put_item(
        TableName=TABLE_LIENS,
        Item={"lien_id": {"S": lien_id}, "restants": {"N": str(restants)}},
    )


def lire_restants(lien_id):
    r = dynamo.get_item(
        TableName=TABLE_LIENS,
        Key={"lien_id": {"S": lien_id}},
        ConsistentRead=True,
    )
    return int(r["Item"]["restants"]["N"])


def prendre_un_telechargement(lien_id):
    """Version correcte : 'verifier et retirer un' en UNE seule operation.
    Renvoie le nombre restant, ou None si le lien est epuise."""
    try:
        r = dynamo.update_item(
            TableName=TABLE_LIENS,
            Key={"lien_id": {"S": lien_id}},
            UpdateExpression="SET restants = restants - :un",
            ConditionExpression="restants > :zero",
            ExpressionAttributeValues={":un": {"N": "1"}, ":zero": {"N": "0"}},
            ReturnValues="UPDATED_NEW",
        )
        return int(r["Attributes"]["restants"]["N"])
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise


def prendre_un_telechargement_naif(lien_id):
    """Version FAUSSE : on lit, puis on ecrit. Sert a montrer le probleme."""
    restants = lire_restants(lien_id)
    if restants <= 0:
        return None
    dynamo.update_item(
        TableName=TABLE_LIENS,
        Key={"lien_id": {"S": lien_id}},
        UpdateExpression="SET restants = :n",
        ExpressionAttributeValues={":n": {"N": str(restants - 1)}},
    )
    return restants - 1


# Credit d'ecriture quotidien 
from datetime import datetime, timezone

TABLE_CREDITS = "credits"
LIMITE_JOUR = 10_000


def jour_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _cle_credit(email, jour):
    return {"credit_id": {"S": f"{email.lower()}#{jour or jour_utc()}"}}


def consommer_credit(email, n, jour=None):
    """Retire n caracteres du credit du jour, en une seule operation.
    Renvoie le total utilise apres l'operation, ou None si refuse."""
    if n <= 0:
        raise ValueError("n doit etre positif")
    if n > LIMITE_JOUR:
        return None
    try:
        r = dynamo.update_item(
            TableName=TABLE_CREDITS,
            Key=_cle_credit(email, jour),
            UpdateExpression="SET utilises = if_not_exists(utilises, :zero) + :n",
            ConditionExpression="attribute_not_exists(utilises) OR utilises <= :max",
            ExpressionAttributeValues={
                ":zero": {"N": "0"},
                ":n": {"N": str(n)},
                ":max": {"N": str(LIMITE_JOUR - n)},
            },
            ReturnValues="UPDATED_NEW",
        )
        return int(r["Attributes"]["utilises"]["N"])
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise


def lire_credit(email, jour=None):
    r = dynamo.get_item(
        TableName=TABLE_CREDITS, Key=_cle_credit(email, jour), ConsistentRead=True
    )
    return int(r["Item"]["utilises"]["N"]) if "Item" in r else 0


def rembourser_credit(email, n, jour=None):
    """Rend n caracteres au credit du jour (sans jamais descendre sous 0)."""
    try:
        dynamo.update_item(
            TableName=TABLE_CREDITS,
            Key=_cle_credit(email, jour),
            UpdateExpression="SET utilises = utilises - :n",
            ConditionExpression="attribute_exists(utilises) AND utilises >= :n",
            ExpressionAttributeValues={":n": {"N": str(n)}},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


# ---------------- Liens de telechargement complets ----------------

def creer_lien_complet(lien_id, doc_id, createur, maximum):
    dynamo.put_item(
        TableName=TABLE_LIENS,
        Item={
            "lien_id": {"S": lien_id},
            "doc_id": {"S": doc_id},
            "createur": {"S": createur},
            "maximum": {"N": str(maximum)},
            "restants": {"N": str(maximum)},
        },
        ConditionExpression="attribute_not_exists(lien_id)",
    )


def _lien_depuis_item(item):
    return {
        "lien_id": item["lien_id"]["S"],
        "doc_id": item.get("doc_id", {}).get("S", ""),
        "createur": item.get("createur", {}).get("S", ""),
        "maximum": int(item.get("maximum", {}).get("N", "0")),
        "restants": int(item["restants"]["N"]),
    }


def lire_lien(lien_id):
    r = dynamo.get_item(
        TableName=TABLE_LIENS, Key={"lien_id": {"S": lien_id}}, ConsistentRead=True
    )
    return _lien_depuis_item(r["Item"]) if "Item" in r else None


def lister_liens():
    liens, depart = [], None
    while True:
        params = {"TableName": TABLE_LIENS}
        if depart:
            params["ExclusiveStartKey"] = depart
        r = dynamo.scan(**params)
        liens += [_lien_depuis_item(i) for i in r["Items"]]
        depart = r.get("LastEvaluatedKey")
        if not depart:
            return liens
