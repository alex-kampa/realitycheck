Using Reality Check from a contract
=====================================

Fetching information
--------------------

The simplest way use for Reality Check is to fetch some information for a question that has already been posted using the DApp.

Hovering your mouse over the "..." mark in the upper right-hand corner of a question will show you the question ID and the hash of the question content.

Fetching the answer to a particular question
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Each question can be referred to by its ``question_id``, which is a ``bytes32``. 

There is only one question with any given ``question_id``, and there can only be one corresponding answer.

You can fetch the final answer for a question by calling 

.. code-block:: javascript
   :linenos:

   bytes32 response = getFinalAnswer(bytes32 question_id);


This will return ``bytes32`` data, or throw an error (``revert``) if the question does not exist or has not been finalized. 

A (yes/no) question would normally be cast to a ``uint256`` type, resulting in ``1`` or ``0``.

If you want numerical data, you will usually cast the result to either ``uint256`` or ``int256``.

A single choice from a list of options will return an ID representing a zero-based index.

Who won the US presidential election?
 * 0: Hillary Clinton
 * 1: Donald Trump
 * 2: Other

A response of ``1`` would indicate the result `Donald Trump`.

A multiple-choice list will be indexed as follows:

Which of the following words did Donald Trump use in his inauguration speech?
 * 1: Bigly
 * 2: Deplorable
 * 4: Hillary
 * 8: Twitter

For example, a response of ``9`` would indicate the answers Bigly (``1``) and Twitter (``8``).


Asking questions
----------------

You can ask a new question by calling the ``askQuestion()`` function. 

The content of the question defined as a combination of a numerical ``template_id`` and a ``string`` of parameters.

.. code-block:: javascript
   :linenos:

   function askQuestion(
      uint256 template_id, 
      string question, 
      address arbitrator, 
      uint32 timeout, 
      uint32 opening_ts, 
      uint256 nonce
   )
   returns (bytes32 question_id);

Any ETH you send with this call will be assigned as a reward to whoever answers the question.

The ``bytes32`` ID that will be returned is made by hashing the parameters, plus ``msg.sender``.

The ``nonce`` is a user-supplied number that can be used to disambiguated deliberate repeated uses of the same question. You can use ``0`` if you never intend to ask the same question with the same settings twice.


Accepting an answer only if something has happened
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Once a question has been created, it can be answered immediately. 

In many cases you are not interested in the result of a particular question until it has a particular answer. For example, if you have a contract insuring against my house burning down, you are only interested in the result if my house burned down. You don't care about all the times in between setting up the policy and claiming when my house didn't burn down. 

You may also want to screen out results indicating "unknown" or "no way to tell" or "hasn't happened yet".

One approach is that instead of waiting for the result of a specific ``question_id``, you specify the type of question you want, then wait for a user to send you a question ID with the appropriate content and settings.

To make this easier, we provide a method called ``getFinalAnswerIfMatches()``. This will throw an error not only if the question is not yet answered, but also if the content doesn't match, the bond or timeout is too low, or the arbitrator is not the one you expect.

.. code-block:: javascript
   :linenos:

    function getFinalAnswerIfMatches(
        bytes32 question_id, 
        bytes32 content_hash, 
        address arbitrator, 
        uint256 min_timeout, 
        uint256 min_bond
    ) returns (bytes32 answer)

You can then screen ``answer`` in your contract and only act on results that your contract is interested in.

Getting someone else to ask the question at the right time
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You may also want to incentivize someone to ask the question at the appropriate time, post the initial answer with a sufficient bond, and (optionally) send the result to your contract.

For these situations we provide a separate contract called a `MetaQuestion`.

This allows you to say, "I will pay to get an answer to this question, with a minimum bond of x and timeout of y, but only once it has an answer in a particular range".

.. code-block:: javascript
   :linenos:

   function askQuestion(
      uint256 template_id, 
      string question, 
      address arbitrator, 
      uint256 timeout, 
      uint256 min_bond, 
      uint256 min_answer, 
      uint256 max_answer, 
      uint256 callback_gas
   )
   returns (bytes32 meta_question_id);

The ETH you send with this call will be assigned as a reward to whoever asks the question, and supplies the first answer, along with a bond.

This also includes a ``callback_gas`` parameter. If specified, this allows you to request that somebody calls your contract with the result, once it is known. It should specify the amount of gas required to call your contract with the result, and make it do whatever you need it to do.

Your callback function should look like this:

.. code-block:: javascript
   :linenos:

   function __realitycheck_callback(
      bytes32 meta_question_id,
      bytes32 answer
   )

Creating templates
------------------

A template can be created by calling ``createTemplate("template")``, where "template" is the JSON template. This returns a numerical ID.


If you want to create many similar requests, it will be more efficient to create your own template. For example, a flight insurance app might have:

.. code-block:: json
   :linenos:

    {
        "title": "Was flight %s on date %s delayed by more than 3 hours?", 
        "type": "bool", 
        "category": "flight-information"
    }


This can then by called with a string including only the flight number, the delimiter and the date, eg:
    ``MH17␟2017-12-01``


Making sure a question has an answer
------------------------------------

As discussed in :doc:`availability`, when a question is asked, the answer may be "don't know" or "don't understand" or "this isn't settled yet". Contracts relying on Reality Check for information need to be designed to take account of this possibility.

After settlement Reality Check will preserve information about the ``content_hash_, ``arbitrator``, ``timeout``, ``finalization_ts`` (finalization timestamp) and highest-posted ``bond``. Contracts can either check this information directly or pass their requirements to ``getFinalAnswerIfMatches()``.

We also provide a wrapper contract that will allow contracts to request an answer meeting its conditions. This allows consumer contracts to send a request and receive a callback, sent by an arbitrary user in return for a fee, on a similar model to the Ethereum Alarm Clock.

